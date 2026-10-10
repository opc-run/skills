#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc-run-super-brainstorm / scripts / opc_client.py

OPC.run 超级智囊团 Open API 轻量客户端：**零第三方依赖**（仅 Python 标准库），无需 pip install。

职责：
  1. 解析 Base URL / API Key（环境变量 -> 本地配置文件 -> 匿名）
  2. 请求 Open API 并做统一错误归一化（鉴权失败 / 配额耗尽 / 网络异常 / 未找到）
  3. 解析并上报配额响应头（X-Quota-*），余额不足时输出注册引导
  4. 本地磁盘缓存：导师名录 / 已完成的讨论结果在 TTL 内不重复联网
  5. 离线模式：只读缓存，完全不消耗配额

给调用方的约定：
  - 网络类错误统一抛 ApiError 子类，脚本以非零退出码结束并把**给用户看的话**打到 stdout
  - 日志 / 配额提示打到 stderr，不污染结构化输出

★ 本文件与 opc-run-github-projects-radar/scripts/opc_client.py 是**手工同步的两份拷贝**
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
SKILL_NAME = "超级智囊团"
SKILL_SLUG = "opc-run-super-brainstorm"
USER_AGENT = "%s/%s (+https://opc.run/session)" % (SKILL_SLUG, VERSION)

DEFAULT_BASE_URL = "https://opc.run"
# 统一前缀，**不含 /skill 段** —— 调用方传入的 path 是完整业务路径
# （如 "/skill/board/ask"、"/skill/quota"），避免在两处各带一段拼出 /skill/skill/...
API_PREFIX = "/api.v1/open"

# ── 来源参数：指向站内的链接由脚本统一拼接 ──
SOURCE_PARAM = "skill"


def with_source(url: str) -> str:
    """给站内链接追加 from=skill；已带 query 的链接用 & 拼接。"""
    if not url or "from=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return "%s%sfrom=%s" % (url.split("#")[0], separator, SOURCE_PARAM)


# ── 引导链接（★ 一律从这里取，不要在别处再拼一份）──
# 超级智囊团的产品介绍页（SSR，公开）
INTRO_URL = with_source("https://opc.run/session")
# 站内工作台：发起讨论 / 继续追问的入口
WORKSPACE_URL = with_source("https://opc.run/app/session/list")
# 注册：return_url 让注册/登录后直接回落到智囊团工作台，少一步导航
REGISTER_URL = (with_source("https://opc.run/app/passport")
                + "&return_url=%2Fapp%2Fsession%2Flist")
# 领取/管理 API Key（提升 Skill 每日额度）
API_KEYS_URL = with_source("https://opc.run/app/profile/api-keys")
# 我的点数（点数不足时的引导落点：每日签到 / 邀请好友在此领点）
POINTS_URL = with_source("https://opc.run/app/profile/points")

# 站内条款页（SSR，路由 GET /about/terms）
# ★ 该路径被本 Skill 写死引用，站点改路由必须同步改这里，否则已发布 Skill 的外链会 404
TERMS_URL = os.getenv("OPCRUN_TERMS_URL", "https://opc.run/about/terms")

# 讨论内容由 AI 生成 —— 只在真正输出了发言时补一句，不每题都念
# ★ 只提"讨论"不提"决议"：Skill 侧不给决议，提示里说决议会显得前后矛盾
AI_NOTE = "注：以上讨论由 AI 生成，仅供参考，不构成投资、法律或商业决策建议。"

# 若部署方希望每条输出都带整段免责，设 OPCRUN_LEGAL_FOOTER=1
DISCLAIMER_SHORT = (
    "免责声明：本 Skill 的讨论由 AI 生成，仅供参考，不构成投资、法律或商业决策建议。"
)


def legal_footer_enabled() -> bool:
    return os.getenv("OPCRUN_LEGAL_FOOTER", "").strip() in ("1", "true", "yes")


# 本地状态目录
# ★ 默认 ~/.opc_run_skill：API Key 与客户端标识由 OPC.run 系列 Skill **共用**
#   （在智囊团里配的 Key，开源榜直接可用）；想各自独立就设 OPCRUN_HOME。
# ★ 缓存**按 Skill 分目录**：`cache-clear` 与「本地缓存 N 条」只作用于本 Skill，
#   不会把另一个 Skill 缓存过的内容一起清掉、也不会把人家的条数算进来。
#   旧版扁平缓存（~/.opc_run_skill/cache/*.json）不再读取 —— 讨论缓存 TTL 只有 24 小时，
#   自然过期即可，需要立刻回收就手动删掉那些文件。
HOME_DIR = Path(os.getenv("OPCRUN_HOME", str(Path.home() / ".opc_run_skill")))
CACHE_DIR = Path(os.getenv("OPCRUN_CACHE_DIR", str(HOME_DIR / "cache" / SKILL_SLUG)))
KEY_FILE = Path(os.getenv("OPCRUN_KEY_FILE", str(HOME_DIR / "api_key")))
# radar 旧版默认目录里的 Key：只读兼容（~/.opc_projects_radar 是 radar 早期的默认位置）。
# 本 Skill 从未往那儿写过，但老 radar 用户可能只有这一份 Key —— 读它，
# 「Key 两个 Skill 共用」对这批用户才成立。新写入一律落到共享目录。
LEGACY_KEY_FILE = Path.home() / ".opc_projects_radar" / "api_key"
CLIENT_ID_FILE = HOME_DIR / "client_id"


def client_id() -> str:
    """
    本地持久化的安装标识（UUIDv4），随每次请求上报 X-OPC-Client-Id。

    ★ 匿名提交讨论后，**只有同一个 client_id 能查回结果** —— 服务端没有账号维度
      可判断归属，靠它做匿名归属校验。删除 ~/.opc_run_skill/client_id 即视为换了一台机器，
      此前匿名提交的讨论就查不回来了（带 API Key 提交的不受影响）。
    """
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
CODE_POINTS_NOT_ENOUGH = 100117   # 账号点数不足
CODE_POINTS_FROZEN = 100118       # 点数账户被冻结

# 默认缓存 TTL（秒）
TTL_MENTORS = 24 * 3600      # 导师名录是静态的
TTL_DISCUSSION = 24 * 3600   # 已完成的讨论不会再变
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
    """资源不存在（如 task_id 有误）。"""

    exit_code = 4


class PointsRequired(ApiError):
    """
    账号点数不足 / 账户被冻结 —— 提交被拒，**没有扣点也没有消耗额度**。

    单列一个类型：这条路径**只有注册用户会碰到**（匿名 userId=0 时服务端直接放行），
    而它恰恰是最有价值的那批人 —— 报错文案必须能告诉他们下一步干什么，
    而不是干巴巴抛一句「点数不足」。
    """

    exit_code = 6


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
        # plan / identity 头都可能被 CDN 或网关剥掉。
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

        ★ 按**身份**区分话术：
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
      **字段名原样**输出（`Mentors` 而不是 `mentors`），客户端按小写取就全取不到 ——
      而且不会报错，表现是"讨论跑完了但一条内容都没有"，退出码还是 0。
      这个坑真实踩过：讨论内容整场丢失。

    ★ 做法：只降级首字母（`Mentors`→`mentors`），保留已有的正确键。
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


# 生成"下一步命令"用的解释器名（理由同 radar：Windows 上只有 python，写死 python3 会让用户照抄失败）
# ★ Windows 上 sys.executable 是 python.exe：去掉 .exe 再输出，粘贴到 cmd / PowerShell /
#   Git Bash 都不用改；取不到就退回 python3。
_bin = os.path.basename(sys.executable or "").strip()
if _bin.lower().endswith(".exe"):
    _bin = _bin[:-4]
PY_BIN = _bin or "python3"


def cmd_line(script: str, args: str = "") -> str:
    """脚本输出里的"下一步命令"统一走这里。"""
    return ("%s scripts/%s %s" % (PY_BIN, script, args)).rstrip()


def resolve_api_key() -> str:
    """
    API Key 解析优先级：
      1. 环境变量 OPCRUN_API_KEY（推荐，不落盘）
      2. 共享目录 ~/.opc_run_skill/api_key（POSIX 下写入时自动 600 权限）
      3. radar 旧目录 ~/.opc_projects_radar/api_key（只读兼容，见 LEGACY_KEY_FILE）
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
    """把 API Key 落到本地文件（供 CLI 的 auth 子命令使用）。"""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip(), encoding="utf-8")
    try:
        os.chmod(str(KEY_FILE), 0o600)
    except OSError:
        pass


def key_perm_note() -> str:
    """
    Key 文件权限的**如实**描述。

    ★ 之前在所有平台都打印"权限 600"，但 Windows 上 os.chmod 只能切换只读位
      （实测文件权限仍是 0o666）。宣称"600"是虚假承诺 —— 用户会以为只有自己能读。
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
    # ★ 返回结构保持不变（get() 依赖 _cache_age_seconds）；字段归一化在消费点做
    return payload


def _write_cache(path: str, params: dict, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target = _cache_file(path, params)
        # 先写临时文件再原子替换：写一半中断（Ctrl-C）不会留下坏 JSON
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(target))
    except OSError:
        pass


def _headers() -> dict:
    return {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "X-OPC-Source": SOURCE_PARAM,
        "X-OPC-Skill": SKILL_SLUG,
        "X-OPC-Skill-Version": VERSION,
        "X-OPC-Client-Id": client_id(),
    }


# 发起请求的默认超时（秒）。
# ★ 给到 5 分钟：讨论链路背后是串行 LLM 调用，议题上下文一长（导师多 / 轮次多），
#   服务端响应会明显变慢——60 秒级别的超时会在真正"还在干活"时把请求掐断，
#   用户看到的是"请求失败"，实际只是慢。轮询用的轻查询远到不了这个上限，不受影响。
REQUEST_TIMEOUT_DEFAULT = 300


def _request(method: str, path: str, params: dict = None, payload: dict = None,
             timeout: int = REQUEST_TIMEOUT_DEFAULT) -> dict:
    """
    发起一次真实 HTTP 请求，返回解析后的完整 JSON body（含 code/message/data）。

    遥测参数统一带 `_` 前缀（`_src` / `_skill` / `_sv`），与业务参数分层，
    调用方一眼能看出这些是内部标识。
    """
    url = "%s%s%s" % (base_url(), API_PREFIX, path)
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    query.update({"_src": SOURCE_PARAM, "_skill": SKILL_SLUG, "_sv": VERSION})
    url = "%s?%s" % (url, urllib.parse.urlencode(query))

    headers = _headers()
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    key = resolve_api_key()
    if key:
        headers["Authorization"] = "Bearer %s" % key

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            response_headers = resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        response_headers = exc.headers
        status = exc.code
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        message = body.get("message") or raw[:200] or "HTTP %s" % status
        quota = Quota.from_headers(response_headers)
        if status == 401:
            raise AuthError(message or "API Key 无效或已被禁用")
        if status == 429:
            # ★ 后端 429 的 data 里有完整引导（hint / register_url / apikeys_url / plan / reset_at），
            # 必须接住传下去 —— 自己拼话术会跟后端文案漂移，还会丢掉精确的 reset_at
            data_body = body.get("data") or {}
            raise QuotaExceeded(
                message or "今日请求额度已用完",
                hint=data_body.get("hint") or quota.low_balance_hint(),
                reset_at=data_body.get("reset_at") or quota.reset_at,
                plan=data_body.get("plan") or quota.plan,
                register_url=data_body.get("register_url", ""),
                apikeys_url=data_body.get("apikeys_url", ""),
            )
        if status == 404:
            raise NotFoundError("接口不存在：%s" % path)
        if status == 402:
            # 与 body 里的 100117 走同一个出口，客户端才能给出"没扣点、去签到"的引导
            raise PointsRequired(message or "点数不足")
        raise ApiError("服务端返回 HTTP %s：%s" % (status, message))
    except urllib.error.URLError as exc:
        raise NetworkError("无法连接 %s（%s）。请检查网络，稍后重试。" % (base_url(), exc.reason))
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
        # ★ 归一化在这里做一次：后面所有消费点（get / post / 缓存）都拿到同一形状
        return {"data": normalize(body.get("data")), "quota": quota, "raw": body}

    if code == CODE_UNAUTHORIZED:
        raise AuthError(message or "API Key 无效或已过期")
    if code == CODE_QUOTA_EXCEEDED:
        data_body = body.get("data") or {}
        raise QuotaExceeded(
            message or "今日请求额度已用完",
            hint=data_body.get("hint") or quota.low_balance_hint(),
            reset_at=data_body.get("reset_at") or quota.reset_at,
            plan=data_body.get("plan") or quota.plan,
            register_url=data_body.get("register_url", ""),
            apikeys_url=data_body.get("apikeys_url", ""),
        )
    if code == CODE_NOT_FOUND:
        raise NotFoundError(message or "没有找到对应的讨论")
    if code in (CODE_POINTS_NOT_ENOUGH, CODE_POINTS_FROZEN):
        # 提交被拒：没有扣点、没有消耗额度 —— 引导去领点数 / 站内继续
        raise PointsRequired(message or "点数不足")
    raise ApiError("接口返回错误（code=%s）：%s" % (code, message or "未知错误"))


def _report_quota(quota: Quota) -> None:
    desc = quota.describe()
    if desc:
        log("🔢 %s" % desc)
    hint = quota.low_balance_hint()
    if hint:
        log(hint)


def get(path: str, params: dict = None, ttl: int = TTL_NONE, refresh: bool = False,
        offline: bool = False, quota_log: bool = True) -> dict:
    """
    调用 Open API 的 GET 接口，返回：
        {"data": <业务数据>, "quota": Quota, "cached": bool, "cache_age": int}

    :param ttl:      缓存有效期（秒），0 表示不缓存
    :param refresh:  True 时忽略缓存强制联网
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
        raise NetworkError("离线模式下没有该查询的缓存。请先联网执行一次，或去掉 --offline 参数。")

    result = _request("GET", path, params)
    if quota_log:
        _report_quota(result["quota"])

    if use_cache:
        _write_cache(path, params, {"data": result["data"]})

    return {"data": result["data"], "quota": result["quota"], "cached": False, "cache_age": 0}


def post(path: str, payload: dict, params: dict = None, quota_log: bool = True,
         timeout: int = REQUEST_TIMEOUT_DEFAULT) -> dict:
    """
    调用 Open API 的 POST 接口（提交议题走这里）。

    ★ 不缓存：提交是写操作，缓存没有意义。
    """
    result = _request("POST", path, params, payload, timeout=timeout)
    if quota_log:
        _report_quota(result["quota"])
    return {"data": result["data"], "quota": result["quota"], "cached": False, "cache_age": 0}


def cached(path: str, params: dict, ttl: int):
    """只读缓存（不联网）。命中返回 data，未命中返回 None。"""
    if not cache_enabled():
        return None
    payload = _read_cache(path, params, ttl)
    if payload is None:
        return None
    # ★ 缓存里存的是服务端原始大小写
    return normalize(payload.get("data"))


def remember(path: str, params: dict, data) -> None:
    """
    把一份**已完成**的响应写进本地缓存。

    ★ 只用于讨论结果，且只在 status 是终态时写 ——
      讨论是增量落库的，进行中的响应会继续变长，
      把它缓存下来等于把半场讨论冻住 24 小时。
    """
    if cache_enabled():
        _write_cache(path, params, {"data": data})


def _format_age(seconds: int) -> str:
    if seconds < 60:
        return "%s 秒" % seconds
    if seconds < 3600:
        return "%s 分钟" % (seconds // 60)
    return "%.1f 小时" % (seconds / 3600)


def cache_stats() -> dict:
    """统计本地缓存条目数与占用，供 cache-list 展示。"""
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
