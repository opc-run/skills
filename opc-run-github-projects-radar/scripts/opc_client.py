#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc-run-github-projects-radar / scripts / opc_client.py

OPC.run 开源精选 Open API 轻量客户端：**零第三方依赖**（仅 Python 标准库），无需 pip install。

职责：
  1. 解析 Base URL / API Key（环境变量 -> 本地配置文件 -> 匿名）
  2. 请求 Open API 并做统一错误归一化（鉴权失败 / 配额耗尽 / 网络异常 / 404）
  3. 解析并上报配额响应头（X-Quota-*），余额不足时输出注册引导
  4. 本地磁盘缓存：同一查询在 TTL 内不重复消耗配额
  5. 离线模式：只读缓存，完全不消耗配额

给调用方的约定：
  - 网络类错误统一抛 ApiError 子类，脚本以非零退出码结束并把**给用户看的话**打到 stdout
  - 日志 / 配额提示打到 stderr，不污染结构化输出

★ 本文件与 opc-run-super-brainstorm/scripts/opc_client.py 是**手工同步的两份拷贝**
  （Skill 必须单目录自包含，无法跨目录 import）。功能性改动（normalize / 错误归一化 /
  Key 解析 / 缓存读写）必须两边一起改；允许的差异仅限：URL 常量、TTL 分级、
  PointsRequired / post()（仅智囊团有提交与扣点）、个别文案。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

def _meta_version() -> str:
    """从 skill 根目录的 _meta.json 读版本号（唯一事实源）。

    升级时的同步点（共 3 处，都要跟着 _meta.json 一起改）：
      1. SKILL.md frontmatter 的 metadata.version
      2. bootstrap.py 的 CHANGELOG 新增/修改对应版本的 key
      3. 下方 VERSION 的兜底串（仅在读不到 _meta 时使用）
    """
    try:
        meta_path = Path(__file__).resolve().parent.parent / "_meta.json"
        return str((json.loads(meta_path.read_text(encoding="utf-8")) or {}).get("version") or "")
    except (OSError, ValueError):
        return ""


VERSION = os.getenv("OPCRUN_VERSION", "") or _meta_version() or "1.0.0"
SKILL_NAME = "GitHub精选开源项目排行和搜索"
SKILL_SLUG = "opc-run-github-projects-radar"
USER_AGENT = "%s/%s (+https://opc.run/projects)" % (SKILL_SLUG, VERSION)

DEFAULT_BASE_URL = "https://opc.run"
# 统一前缀，**不含 /skill 段** —— 调用方传入的 path 是完整业务路径
# （如 "/skill/projects/semantic"、"/skill/quota"），与契约 §4 的路径逐字对应，
# 避免前缀里带一段、路径里再带一段导致 /skill/skill/... 这类拼接错误。
API_PREFIX = "/api.v1/open"

PROJECTS_URL = "https://opc.run/projects"

# ── 来源参数：指向站内的链接由脚本统一拼接 ──
SOURCE_PARAM = "skill"


def with_source(url: str) -> str:
    """给站内链接追加 from=skill；已带 query 的链接用 & 拼接。"""
    if not url or "from=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return "%s%sfrom=%s" % (url.split("#")[0], separator, SOURCE_PARAM)


# ── 免责相关的短提示 ──
# 原则：**完整免责条款留给 Skill 详情页（README）与站内条款页，不塞进每次对话输出**。
# 只有真正输出了 AI 生成内容 / 协议判断时，才在答案末尾补一句短提示，避免噪音。
# 站内条款页：https://opc.run/about/terms（SSR 页面，路由 GET /about/terms）
# ★ 该路径被本 Skill 写死引用，站点改路由必须同步改这里，否则已发布 Skill 的外链会 404
TERMS_URL = os.getenv("OPCRUN_TERMS_URL", "https://opc.run/about/terms")
AI_NOTE = "注：以上评分与建议由 AI 生成，仅供参考，不构成投资或法律意见。"
LICENSE_NOTE = "注：协议与风险等级为自动识别，不构成法律意见；商用前请自行阅读完整 LICENSE。"

# 若部署方希望每条输出都带整段免责，设 OPCRUN_LEGAL_FOOTER=1
DISCLAIMER_SHORT = (
    "免责声明：数据为每日同步快照，Star / 增长请以 GitHub 官方为准；"
    "AI 生成的六维评估与变现建议仅供参考，不构成投资或法律意见；"
    "GitHub® 是 GitHub, Inc. 的商标，本 Skill 与其无隶属、授权或背书关系。"
)


def legal_footer_enabled() -> bool:
    return os.getenv("OPCRUN_LEGAL_FOOTER", "").strip() in ("1", "true", "yes")

# 注册 / 领 Key 入口
# return_url 让注册/登录后直接回落到 API Keys 领取页，缩短拿 Key 的路径
REGISTER_URL = (with_source("https://opc.run/app/passport")
                + "&return_url=%2Fapp%2Fprofile%2Fapi-keys")
API_KEYS_URL = with_source("https://opc.run/app/profile/api-keys")

# 本地状态目录
# ★ 默认 ~/.opc_run_skill：API Key 与客户端标识由 OPC.run 系列 Skill **共用**
#   （与 opc-run-super-brainstorm 一致），所以在智囊团里配的 Key，开源榜直接就能用。
#   历史默认是 ~/.opc_projects_radar —— 旧 Key 仍会被读取（见 resolve_api_key 的 LEGACY_KEY_FILE），
#   但新写入一律落到共享目录；想彻底分开就设 OPCRUN_HOME。
# ★ 缓存**按 Skill 分目录**：`cache-clear` 与「本地缓存 N 条」只作用于本 Skill，
#   不会把智囊团缓存过的讨论一起清掉、也不会把人家的条数算进来。
#   旧版扁平缓存（~/.opc_run_skill/cache/*.json）不再读取 —— 项目详情缓存 TTL 24 小时，
#   自然过期即可，需要立刻回收就手动删掉那些文件。
HOME_DIR = Path(os.getenv("OPCRUN_HOME", str(Path.home() / ".opc_run_skill")))
CACHE_DIR = Path(os.getenv("OPCRUN_CACHE_DIR", str(HOME_DIR / "cache" / SKILL_SLUG)))
KEY_FILE = Path(os.getenv("OPCRUN_KEY_FILE", str(HOME_DIR / "api_key")))
# 旧版默认目录里的 Key：只读兼容，不再往那儿写
LEGACY_KEY_FILE = Path.home() / ".opc_projects_radar" / "api_key"
CLIENT_ID_FILE = HOME_DIR / "client_id"


def client_id() -> str:
    """本地随机生成的安装标识；删除 ~/.opc_run_skill/client_id 即重置。"""
    try:
        if CLIENT_ID_FILE.exists():
            value = CLIENT_ID_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    try:
        HOME_DIR.mkdir(parents=True, exist_ok=True)
        CLIENT_ID_FILE.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value

# 业务错误码（与后端一致）
CODE_SUCCESS = 0
CODE_UNAUTHORIZED = 100401
CODE_QUOTA_EXCEEDED = 100429
CODE_NOT_FOUND = 100404

# 默认缓存 TTL（秒）：按数据变动频率分级，目的是把匿名 3 次/天的额度用在刀刃上
TTL_RANKING = 6 * 3600
TTL_SEARCH = 1 * 3600
TTL_STATIC = 24 * 3600
TTL_NONE = 0


class ApiError(Exception):
    """Open API 调用失败的基类。message 可直接展示给用户。"""

    exit_code = 1

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class AuthError(ApiError):
    """API Key 无效 / 被禁用 / 格式错误。"""

    exit_code = 2


class QuotaExceeded(ApiError):
    """当日额度用完（匿名 / 已配置 API Key）。plan 用于区分两类引导话术。"""

    exit_code = 3

    def __init__(self, message: str, hint: str = "", reset_at: str = "", plan: str = "",
                 register_url: str = "", apikeys_url: str = "") -> None:
        super().__init__(message, hint)
        self.reset_at = reset_at
        self.plan = plan
        # 后端 429 data 里的引导链接（匿名身份才有）；客户端常量做兜底
        self.register_url = register_url
        self.apikeys_url = apikeys_url

    @property
    def is_anonymous(self) -> bool:
        return self.plan in ("", "anonymous")


class NotFoundError(ApiError):
    """资源不存在（如 slug 拼错）。"""

    exit_code = 4


class NetworkError(ApiError):
    """网络不可达 / 超时 / 响应非 JSON。"""

    exit_code = 5


class Quota:
    """一次请求返回的配额快照。"""

    def __init__(self, limit=None, remaining=None, reset_at="", identity="", plan="") -> None:
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at
        self.identity = identity
        self.plan = plan

    @classmethod
    def from_headers(cls, headers) -> "Quota":
        def _int(name):
            raw = headers.get(name)
            if raw is None:
                return None
            try:
                return int(raw)
            except ValueError:
                return None

        return cls(
            limit=_int("X-Quota-Limit"),
            remaining=_int("X-Quota-Remaining"),
            reset_at=headers.get("X-Quota-Reset", "") or "",
            identity=headers.get("X-Quota-Identity", "") or "",
            plan=headers.get("X-Quota-Plan", "") or "",
        )

    def is_anonymous(self) -> bool:
        if (self.plan or "") == "anonymous":
            return True
        if self.plan:
            return False
        # plan / identity 头都可能被 CDN 或网关剥掉（实测 429 时存在，但不能赌）。
        # 判不出来时用**本地事实**兜底：配了 Key 就绝不按匿名处理 ——
        # 否则会对已注册用户推"去注册领 Key"，正是话术设计要避免的乌龙。
        return not resolve_api_key()

    def describe(self) -> str:
        if self.remaining is None or self.limit is None:
            return ""
        plan_label = "匿名" if self.is_anonymous() else "已配置 API Key"
        tail = "，重置时间 %s" % self.reset_at if self.reset_at else ""
        return "配额[%s] %s/%s%s" % (plan_label, self.remaining, self.limit, tail)

    def low_balance_hint(self) -> str:
        """
        余额不足时的引导。返回空串表示无需提示。

        ★ 按**身份**区分话术，别把注册链接推给已注册用户：
          - 匿名用完 → 推注册（这是转化点）
          - 已注册用完 → 只说明恢复时间；再推注册只会让人困惑
        """
        if self.remaining is None:
            return ""
        if self.remaining <= 0:
            if self.is_anonymous():
                return (
                    "⚠️ 匿名额度已用完。[注册 OPC.run 账号并领取免费 API Key](%s) 即可解锁更高额度。"
                    % REGISTER_URL
                )
            return (
                "⚠️ 今日额度已用完，将于 %s 重置；缓存过的内容可用 --offline 离线查看。"
                % (self.reset_at or "明日 0 点")
            )
        if self.remaining <= 1 and self.is_anonymous():
            return (
                "💡 匿名额度仅剩 %s 次/天。[注册账号领取 API Key](%s) 可大幅提升额度（免费）。"
                % (self.remaining, REGISTER_URL)
            )
        return ""


def log(message: str) -> None:
    """提示信息走 stderr，避免污染 stdout 的结构化输出。"""
    if message:
        print(message, file=sys.stderr)


def normalize(data):
    """
    归一化响应字段的大小写。

    ★ 为什么需要：服务端 DTO 里只要有一个字段漏了 `json:"xxx"` tag，Go 就会按
      **字段名原样**输出（`Items` 而不是 `items`），客户端按小写取就全取不到 ——
      而且不会报错，表现是"请求成功了但一条内容都没有"，退出码还是 0。
      这个坑在智囊团侧真实踩过：讨论内容整场丢失。

    ★ 做法：只降级首字母（`Items`→`items`），保留已有的正确键。
      万一以后服务端再漏别的 tag，也会被这里兜住。
    ★ 网络响应与缓存读出都要套（缓存里存的是原始大小写）。
    """
    if not isinstance(data, dict):
        return data
    for key in list(data.keys()):
        if not key or not key[0].isupper():
            continue
        lower = key[0].lower() + key[1:]
        if lower not in data:
            data[lower] = data[key]
    return data


def base_url() -> str:
    return (os.getenv("OPCRUN_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


# 生成"下一步命令"用的解释器名。
# ★ 不要写死 python3：Windows 上常常只有 python，用户照抄写死的命令一定失败，
#   而脚本输出被要求原样保留 —— 写死就等于让用户卡住。取当前解释器名，取不到才退回 python3。
# ★ Windows 上 sys.executable 是 python.exe：去掉 .exe 再输出，粘贴到 cmd / PowerShell /
#   Git Bash 都不用改。
_bin = os.path.basename(sys.executable or "").strip()
if _bin.lower().endswith(".exe"):
    _bin = _bin[:-4]
PY_BIN = _bin or "python3"


def cmd_line(script: str, args: str = "") -> str:
    """脚本输出里的"下一步命令"统一走这里，保证与当前运行环境一致。"""
    return ("%s scripts/%s %s" % (PY_BIN, script, args)).rstrip()


def resolve_api_key() -> str:
    """
    API Key 解析优先级：
      1. 环境变量 OPCRUN_API_KEY（推荐，不落盘）
      2. 共享目录 ~/.opc_run_skill/api_key（与 opc-run-super-brainstorm 共用同一份）
      3. 旧目录 ~/.opc_projects_radar/api_key（只读兼容：本 Skill 早期的默认位置）
      4. 都没有 -> 匿名，每天 3 次
    """
    key = (os.getenv("OPCRUN_API_KEY") or "").strip()
    if key:
        return key
    for path in (KEY_FILE, LEGACY_KEY_FILE):
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:
            continue
    return ""


def save_api_key(key: str) -> None:
    """把 API Key 落到共享目录（供 CLI 的 auth 子命令使用）。"""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip(), encoding="utf-8")
    try:
        os.chmod(str(KEY_FILE), 0o600)
    except OSError:
        pass


def key_perm_note() -> str:
    """
    Key 文件权限的**如实**描述。

    ★ 不要在所有平台都宣称"权限 600"：Windows 上 os.chmod 只能切换只读位
      （实测权限仍是 0o666），宣称 600 是虚假承诺 —— 用户会以为只有自己能读。
    """
    if os.name == "posix":
        return "已按 POSIX 惯例设为 600"
    return "已保存（Windows 下文件权限由所在目录的 ACL 决定，脚本无法设 600）"


def mask_key(key: str) -> str:
    """脱敏展示，日志里绝不出现完整 Key。"""
    if len(key) <= 10:
        return "*" * len(key)
    return "%s...%s" % (key[:6], key[-4:])


def cache_enabled() -> bool:
    return os.getenv("OPCRUN_NO_CACHE", "").strip() not in ("1", "true", "yes")


def _cache_file(path: str, params: dict) -> Path:
    normalized = json.dumps(
        {
            "base": base_url(),
            "path": path,
            "params": {k: v for k, v in sorted((params or {}).items()) if v not in (None, "")},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / ("%s.json" % digest)


def _read_cache(path: str, params: dict, ttl: int):
    """命中缓存返回 payload dict，否则返回 None。"""
    if ttl <= 0:
        return None
    cache_file = _cache_file(path, params)
    if not cache_file.exists():
        return None
    age = time.time() - cache_file.stat().st_mtime
    if age > ttl:
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    payload["_cached"] = True
    payload["_cache_age_seconds"] = int(age)
    return payload


def _write_cache(path: str, params: dict, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target = _cache_file(path, params)
        # 先写临时文件再原子替换：写一半中断（断电 / Ctrl-C）不会留下坏 JSON，
        # 否则下次读取 json.loads 失败被当"未命中"，明明有缓存却重新联网白烧配额
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(target))
    except OSError:
        # 缓存写失败不影响主流程
        pass


def _request(path: str, params: dict) -> dict:
    """
    发起一次真实 HTTP 请求，返回解析后的完整 JSON body（含 code/message/data）。

    每次请求附带调用来源标识：
      - 查询串：`_src=skill`、`_skill=<slug>`、`_sv=<skill 版本>`
      - 请求头：`X-OPC-Source` / `X-OPC-Skill` / `X-OPC-Skill-Version` / `X-OPC-Client-Id`

    内部参数统一加 `_` 前缀（`_src` / `_skill` / `_sv`），与业务参数（q/tag/limit/sort/slug）
    在视觉上分层：调用方一眼能看出这些是内部标识，不会误当成筛选条件去传。
    """
    url = "%s%s%s" % (base_url(), API_PREFIX, path)
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    query.update({"_src": SOURCE_PARAM, "_skill": SKILL_SLUG, "_sv": VERSION})
    url = "%s?%s" % (url, urllib.parse.urlencode(query))

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "X-OPC-Source": SOURCE_PARAM,
        "X-OPC-Skill": SKILL_SLUG,
        "X-OPC-Skill-Version": VERSION,
        "X-OPC-Client-Id": client_id(),
    }
    key = resolve_api_key()
    if key:
        headers["Authorization"] = "Bearer %s" % key

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            response_headers = resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        response_headers = exc.headers
        status = exc.code
        body = {}
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        message = body.get("message") or raw[:200] or "HTTP %s" % status
        quota = Quota.from_headers(response_headers)
        if status == 401:
            # message 直接用服务端文案（本身已是完整句子，前面再拼前缀会重复）
            raise AuthError(message or "API Key 无效或已被禁用")
        if status == 429:
            # ★ 后端 429 的 data 里有完整引导（hint/register_url/apikeys_url/plan/reset_at），
            # 必须接住传下去 —— 只用 header 自己拼话术，会跟后端文案漂移，
            # 还会丢掉后端给的精确 reset_at 与身份
            data = body.get("data") or {}
            raise QuotaExceeded(
                message or "今日请求额度已用完",
                hint=data.get("hint") or quota.low_balance_hint(),
                reset_at=data.get("reset_at") or quota.reset_at,
                plan=data.get("plan") or quota.plan,
                register_url=data.get("register_url", ""),
                apikeys_url=data.get("apikeys_url", ""),
            )
        if status == 404:
            # ★ 只报 path，不报完整 url：url 里带着 _src / _skill / _sv 等内部遥测参数，
            #   整条回显给用户既看不懂又是噪音（且与智囊团侧口径不一致）
            raise NotFoundError("接口不存在：%s" % path)
        raise ApiError("服务端返回 HTTP %s：%s" % (status, message))
    except urllib.error.URLError as exc:
        raise NetworkError(
            "无法连接 %s（%s）。请检查网络，稍后重试。" % (base_url(), exc.reason)
        )
    except Exception as exc:  # noqa: BLE001 - 兜底：超时 / 编码异常统一归网络错误
        raise NetworkError("请求失败：%s" % exc)

    try:
        body = json.loads(raw)
    except ValueError:
        raise NetworkError("服务返回了非 JSON 内容（可能被网关拦截）：%s" % raw[:200])

    quota = Quota.from_headers(response_headers)
    code = body.get("code", CODE_SUCCESS)
    message = body.get("message") or ""

    if code == CODE_SUCCESS:
        # ★ 归一化在这里做一次：后面所有消费点（get / 缓存）都拿到同一形状
        return {"data": normalize(body.get("data")), "quota": quota}

    if code == CODE_UNAUTHORIZED:
        raise AuthError(message or "API Key 无效或已过期")
    if code == CODE_QUOTA_EXCEEDED:
        data = body.get("data") or {}
        raise QuotaExceeded(
            message or "今日请求额度已用完",
            hint=data.get("hint") or quota.low_balance_hint(),
            reset_at=data.get("reset_at") or quota.reset_at,
            plan=data.get("plan") or quota.plan,
            register_url=data.get("register_url", ""),
            apikeys_url=data.get("apikeys_url", ""),
        )
    if code == CODE_NOT_FOUND:
        raise NotFoundError(message or "没有找到对应内容")
    raise ApiError("接口返回错误（code=%s）：%s" % (code, message or "未知错误"))


def get(path: str, params: dict = None, ttl: int = TTL_NONE, refresh: bool = False,
        offline: bool = False, quota_log: bool = True) -> dict:
    """
    调用 Open API，返回：
        {"data": <业务数据>, "quota": Quota, "cached": bool, "cache_age": int}

    :param ttl:      缓存有效期（秒），0 表示不缓存
    :param refresh:  True 时忽略缓存强制联网（会消耗配额）
    :param offline:  True 时只读缓存，未命中直接报错（不消耗配额）
    """
    params = params or {}
    use_cache = cache_enabled() and ttl > 0

    if use_cache and not refresh:
        cached = _read_cache(path, params, ttl)
        if cached is not None:
            if quota_log:
                log("📦 命中本地缓存（%s 前），本次不消耗配额" % _format_age(cached["_cache_age_seconds"]))
            return {
                # ★ 缓存里存的是服务端原始大小写，取出时统一归一化
                "data": normalize(cached.get("data")),
                "quota": Quota(),
                "cached": True,
                "cache_age": cached["_cache_age_seconds"],
            }

    if offline:
        raise NetworkError(
            "离线模式下没有该查询的缓存。请先联网执行一次，或去掉 --offline 参数。"
        )

    result = _request(path, params)
    quota = result["quota"]

    if use_cache:
        _write_cache(path, params, {"data": result["data"]})

    if quota_log:
        desc = quota.describe()
        if desc:
            log("🔢 %s" % desc)
        hint = quota.low_balance_hint()
        if hint:
            log(hint)

    return {"data": result["data"], "quota": quota, "cached": False, "cache_age": 0}


def cached(path: str, params: dict, ttl: int):
    """只读缓存（不联网）。命中返回 data，未命中返回 None。"""
    if not cache_enabled():
        return None
    payload = _read_cache(path, params, ttl)
    if payload is None:
        return None
    # ★ 缓存里存的是服务端原始大小写
    return normalize(payload.get("data"))


def _format_age(seconds: int) -> str:
    if seconds < 60:
        return "%s 秒" % seconds
    if seconds < 3600:
        return "%s 分钟" % (seconds // 60)
    return "%.1f 小时" % (seconds / 3600)


def cache_stats() -> dict:
    """统计本地缓存条目数与占用，供 usage 子命令展示。"""
    if not CACHE_DIR.exists():
        return {"count": 0, "bytes": 0}
    count = 0
    total = 0
    for item in CACHE_DIR.glob("*.json"):
        count += 1
        try:
            total += item.stat().st_size
        except OSError:
            pass
    return {"count": count, "bytes": total}


def clear_cache() -> int:
    """清空本地缓存，返回删除的文件数。"""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for item in CACHE_DIR.glob("*.json"):
        try:
            item.unlink()
            removed += 1
        except OSError:
            pass
    return removed
