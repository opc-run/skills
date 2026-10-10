#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc-run-github-projects-radar / scripts / projects.py

统一命令行入口：把 OPC.run「开源精选」的能力暴露成若干子命令。

子命令名与 Open API 路径一一对应（同一个概念只有一个名字，避免歧义）：

    python3 scripts/projects.py semantic   <自然语言需求> [--tag=] [--limit=10]     -> /projects/semantic
    python3 scripts/projects.py ranking    [--sort=growth_7d|growth_30d|commercial]  -> /projects/ranking
    python3 scripts/projects.py categories                                            -> /projects/categories
    python3 scripts/projects.py detail     <slug>                                     -> /projects/detail
    python3 scripts/projects.py compare    <slug1> <slug2> [更多 slug...]            -> 复用 detail
    python3 scripts/projects.py quota                                                 -> /skill/quota
    python3 scripts/projects.py auth       <API_KEY> [--status] [--clear]            -> 本地命令，无 API

通用参数：
    --json        输出原始 JSON（供 Agent 自行加工），默认输出 Markdown
    --refresh     忽略本地缓存强制联网（消耗配额）
    --offline     只读本地缓存（零配额消耗）
    --no-cache    本次请求不读不写缓存
    --limit=N     返回条数（最大 20）

退出码：
    0 成功  1 通用失败  2 API Key 无效  3 配额耗尽  4 未找到  5 网络异常
    130 用户 Ctrl-C 中断
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opc_client as client  # noqa: E402
from opc_client import (  # noqa: E402
    API_KEYS_URL,
    PROJECTS_URL,
    REGISTER_URL,
    TTL_RANKING,
    TTL_SEARCH,
    TTL_STATIC,
    ApiError,
)

# 六维商业评估的中文展示名与满分口径
ASSESSMENT_FIELDS = [
    ("pain_point", "痛点强度"),
    ("target_customer", "目标客户清晰度"),
    ("redevelopment", "二次开发可行性"),
    ("solopreneur", "个人可独立完成"),
    ("monetization", "变现空间"),
    ("license", "协议友好度"),
]

SORT_LABELS = {
    "growth_7d": "周增长榜（近 7 天 Star 增速）",
    "growth_30d": "月增长榜（近 30 天 Star 增速）",
    "commercial": "商业价值榜（AI 六维评分）",
}
DEFAULT_SORT = "growth_7d"

# 注意：这里把「时间窗口」和「排序目标」合成**一个**枚举值，而不是分成
# `period=7d|30d` + `sort=growth|commercial` 两个参数 —— 单参数的组合是穷尽的，
# 不会出现「按商业分排序 + 近 7 天」这种语义上没有意义的非法组合，
# 对 Agent 更不容易猜错（它没法外推出 dimension=daily / weekly+commercial 这类值）。

# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def _get(mapping, key, default=""):
    """安全取值：None / 空串统一回落默认值。"""
    if not isinstance(mapping, dict):
        return default
    value = mapping.get(key)
    if value is None or value == "":
        return default
    return value


def _count(value) -> str:
    """大数字压缩展示：3200 -> 3.2k，与站内口径一致。"""
    if value is None or value == "":
        return "-"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number < 1000:
        return str(number)
    if number < 995000:
        # 995000 起就进位到 m，避免 999999 被四舍五入成荒谬的 1000.0k
        return "%.1fk" % (number / 1000.0)
    return "%.1fm" % (number / 1000000.0)


def _stars(item) -> str:
    return _get(item, "stars_display", _count(_get(item, "stars", None)))


def _growth(item, days: int) -> str:
    # 字段名以 Open API 的 ProjectItem 为准（stars_7d_growth），**不是**实体 json tag。
    # 实体的 json tag 是历史遗留的 stars_7_d_growth（orm tag 反而是 stars_7d_growth，
    # 实体自身就不一致）；DTO 用干净命名，由后端做一次映射。
    key = "stars_7d_growth" if days == 7 else "stars_30d_growth"
    value = _get(item, key, None)
    if value is None:
        return "—"
    try:
        return "+{:,}".format(int(value))
    except (TypeError, ValueError):
        return str(value)


def _score(item) -> str:
    value = _get(item, "commercial_score", None)
    if value is None:
        return "—"
    try:
        return "%.2f" % float(value)
    except (TypeError, ValueError):
        return str(value)


def _tags(item) -> str:
    tags = _get(item, "tags", []) or []
    if not isinstance(tags, list):
        return ""
    return "、".join(str(t) for t in tags[:6])


def _repo_label(item) -> str:
    """
    项目名的统一取值：owner/name → full_name → slug。
    DTO 保证 owner/name 存在，但后端个别老数据可能缺，别渲染出 "[/](url)" 这种残标题。
    """
    owner = _get(item, "repo_owner", "")
    name = _get(item, "repo_name", "")
    if owner and name:
        return "%s/%s" % (owner, name)
    return _get(item, "full_name", "") or _get(item, "slug", "") or "未知项目"


def _page_url(item) -> str:
    """
    站内详情页地址（自动追加 from=skill 来源参数）。
    """
    raw = _get(item, "page_url", "%s/%s" % (PROJECTS_URL, _get(item, "slug", "")))
    return client.with_source(raw)


def _source_footer(note: str = "") -> str:
    """
    结尾来源行。**Agent 必须原样保留**。

    默认不塞免责长文（那是 Skill 详情页与站内条款页的职责）；
    部署方如需每条都带，设环境变量 OPCRUN_LEGAL_FOOTER=1。
    """
    head = "数据来源：OPC.run 开源精选 · [opc.run/projects](%s)" % client.with_source(PROJECTS_URL)
    if note:
        head = "%s ｜ %s" % (note, head)
    if client.legal_footer_enabled():
        return "\n\n---\n%s\n⚠️ %s\n" % (head, client.DISCLAIMER_SHORT)
    return "\n\n---\n%s\n" % head


# --------------------------------------------------------------------------
# Markdown 渲染
# --------------------------------------------------------------------------

def render_project_list(items, title: str) -> str:
    """
    检索 / 榜单结果渲染：**四行精简摘要 + 站内详情页超链接**。

    刻意只留「该不该点」的判断依据（Star / 增长 / 商业分 / 语言 / 协议），
    不输出 why_worth_doing、标签、六维评估、切入方向 —— 那些是详情页的内容，
    留在站内把用户导过去。要看就用 `detail <slug>`。

    ★ 链接一律用 Markdown 超链接语法 `[文字](URL)`：URL 藏在链接目标里，
    对话界面渲染出来只有一小段可点文字，不会把一整串地址甩到用户脸上。
    """
    if not items:
        return "没有检索到匹配的项目。换个说法 / 关键词，或去掉 --tag 限制再试。"

    lines = ["### %s（%d 个）" % (title, len(items)), ""]
    for index, item in enumerate(items, 1):
        page = _page_url(item)
        lines.append(
            "**%d. [%s](%s)**" % (index, _repo_label(item), page)
        )
        meta = [
            "⭐ %s" % _stars(item),
            "📈 周 %s / 月 %s" % (_growth(item, 7), _growth(item, 30)),
            "💰 商业分 %s" % _score(item),
        ]
        if _get(item, "language"):
            meta.insert(1, "🔧 %s" % _get(item, "language"))
        if _get(item, "license_risk") == "high":
            meta.append("⚠️ 协议高风险")
        elif _get(item, "license"):
            meta.append("📜 %s" % _get(item, "license"))
        lines.append("  " + " ｜ ".join(meta))

        description = _get(item, "description")
        if description:
            lines.append("  %s" % _truncate(description, 70))
        # 标题即详情页链接，这里再给一个明确的行动入口（Markdown 超链接）
        lines.append("  👉 [查看详情页：六维评估 · 增长曲线 · 变现建议](%s)" % page)
        lines.append("")

    lines.append("🔗 完整榜单与实时增长数据：[opc.run/projects](%s)"
                 % client.with_source(PROJECTS_URL))
    return "\n".join(lines) + _source_footer()


def render_ranking(data, args=None) -> str:
    items = _get(data, "items", []) or []
    sort = getattr(args, "sort", DEFAULT_SORT)
    title = "%s%s" % (SORT_LABELS.get(sort, "榜单"), " · %s" % args.tag if args.tag else " · 全站")
    if not items:
        return ("该榜单暂时没有数据（可能是因为快照积累不足，通常收录 7 天后自动生成）。\n\n"
                "🔗 [在站内查看完整榜单](%s)" % client.with_source(PROJECTS_URL))

    snapshot_date = _get(data, "snapshot_date", "")
    lines = ["### %s Top %d" % (title, len(items))]
    if snapshot_date:
        lines[0] += "（快照日期：%s）" % snapshot_date
    lines.append("")
    # 协议列必须在：商业榜最该让人看到协议友好度（六维之一），高风险协议要一眼可见
    lines.append("| # | 项目 | Star | 周增 | 月增 | 商业分 | 语言 | 协议 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for item in items:
        license = _get(item, "license", "-")
        if _get(item, "license_risk") == "high":
            license = "%s ⚠️" % license
        lines.append(
            "| %s | [%s](%s) | %s | %s | %s | %s | %s | %s |"
            % (
                _get(item, "rank", "-"),
                _repo_label(item),
                _page_url(item),
                _stars(item),
                _growth(item, 7),
                _growth(item, 30),
                _score(item),
                _get(item, "language", "-"),
                license,
            )
        )
    lines.append("")
    lines.append("👉 点击表格中的项目名即进入站内详情页。")
    lines.append("🔗 榜单持续更新，站内可按分类查看：[opc.run/projects](%s)"
                 % client.with_source(PROJECTS_URL))
    return "\n".join(lines) + _source_footer()


def render_detail(data) -> str:
    """
    详情 = **摘要**，不是全文。

    六维逐项得分与依据、最小产品切入方向、变现模式、Star 增长曲线都是站内详情页的内容，
    这里只给「值不值得点进去」的判断依据（客观指标 + 商业总分 + 置信度 + 一句话简介），
    然后把用户送过去。接口层同样不返回这些字段（不是仅靠渲染层隐藏），
    否则 Agent 用 `--json` 就能把全文读出来，漏斗等于失效。
    """
    if not data:
        return "没有找到该项目。"
    lines = [
        "### [%s](%s)" % (_repo_label(data), _page_url(data)),
        "",
        "- 仓库：<%s>" % _get(data, "url"),
        "- Star：%s ｜ Fork：%s ｜ Open Issues：%s"
        % (_stars(data), _count(_get(data, "forks", None)), _count(_get(data, "open_issues", None))),
        "- 增长：近 7 天 %s ｜ 近 30 天 %s" % (_growth(data, 7), _growth(data, 30)),
        "- 语言：%s ｜ 协议：%s（风险：%s）"
        % (_get(data, "language", "-"), _get(data, "license", "-"), _get(data, "license_risk", "-")),
        "- 商业价值评分：**%s / 5**（%s）"
        % (_score(data), _get(data, "commercial_level", "未评级")),
    ]
    confidence = _confidence(data)
    if confidence:
        lines[-1] += " ｜ 评估置信度：%s" % confidence
    if _tags(data):
        lines.append("- 标签：%s" % _tags(data))
    lines.append("")

    description = _get(data, "description")
    if description:
        lines.append("**简介**：%s" % description)
        lines.append("")

    # 明确告知"墙后面是什么"，比单纯说"去看详情页"更能促成点击
    lines.append("🔒 **以下内容在站内详情页，本 Skill 不返回**：")
    lines.append("   %s的逐项得分与依据 · 最小产品切入方向 · 变现模式 · Star 增长曲线"
                 % "、".join(label for _, label in ASSESSMENT_FIELDS))
    lines.append("")

    # 这里仍会输出 AI 生成的商业分与协议判断 → 短免责提示保留
    if _get(data, "commercial_score", None) is not None:
        lines.append(client.AI_NOTE)
    if _get(data, "license") or _get(data, "license_risk"):
        lines.append(client.LICENSE_NOTE)
    lines.append("")
    lines.append("👉 [查看完整评估与切入方向](%s)" % _page_url(data))
    return "\n".join(lines) + _source_footer()


def _confidence(data) -> str:
    """评估置信度：优先读扁平的 assessment_confidence，兼容嵌套的 assessment.confidence。"""
    value = _get(data, "assessment_confidence", None)
    if value is None:
        node = _get(data, "assessment", {}) or {}
        if isinstance(node, dict):
            value = node.get("confidence")
    if value is None:
        return ""
    try:
        return "%.0f%%" % (float(value) * 100)
    except (TypeError, ValueError):
        return ""


def render_compare(items, failed=None) -> str:
    failed = failed or []
    if not items and not failed:
        return "没有可比对的项目。"
    if not items:
        # 防御分支：全部失败时不渲染残缺表格（CLI 路径走不到，单测/复用可能走到）
        lines = ["没有取得任何可比对的项目。", "",
                 "未成功的 slug：%s" % "、".join(failed),
                 "确认正确 slug 后重试，或先 `detail <slug>` 单独验证。"]
        # ★ 也要带来源行：SKILL.md 要求 Agent「保留结尾的来源行」，
        #   这条分支若无来源行，Agent 会去找一个根本不存在的东西
        return "\n".join(lines) + _source_footer()
    lines = ["### 项目横向对比", ""]
    if items:
        # 表头用 _repo_label 兜底，避免个别数据缺 repo_name 时整列表头为空
        lines.append("| 指标 | %s |" % " | ".join(_repo_label(i) for i in items))
        lines.append("|%s" % ("---|" * (len(items) + 1)))

        # 只比客观指标与总分：六维逐项得分同属站内详情页内容，接口不返回
        rows = [
            ("Star 总数", lambda i: _stars(i)),
            ("近 7 天增长", lambda i: _growth(i, 7)),
            ("近 30 天增长", lambda i: _growth(i, 30)),
            ("商业评分", lambda i: _score(i)),
            ("等级", lambda i: _get(i, "commercial_level", "-")),
            ("语言", lambda i: _get(i, "language", "-")),
            ("协议", lambda i: _get(i, "license", "-")),
            ("协议风险", lambda i: _get(i, "license_risk", "-")),
        ]
        for label, extractor in rows:
            lines.append("| %s | %s |" % (label, " | ".join(extractor(i) for i in items)))
        lines.append("")
        lines.append("👉 六维逐项依据、切入方向与变现模式在各自站内详情页：")
        for index, item in enumerate(items, 1):
            lines.append(
                "- [%s](%s)" % (_repo_label(item), _page_url(item))
            )
    # 单个 slug 失败不拖垮整表：成功的照常出，失败的单独列出让用户补 slug
    if failed:
        lines.append("")
        lines.append("⚠️ 以下条目未取得（slug 有误或网络失败，不占用本次对比的其余结果）：%s"
                     % "、".join(failed))
        lines.append("  确认正确 slug 后可单独执行 `detail <slug>` 再重新对比（已成功的部分有缓存，不重复消耗配额）。")
    return "\n".join(lines) + _source_footer()


def _quote_tag_url(raw) -> str:
    """
    分类页 URL 的路径统一百分号编码（保留 /），且必须**幂等**。

    ★ 先 unquote 再 quote，不能只 quote：后端 SkillCategories 已经编码过一次
      （skillController/project.go：projectOrigin + "/projects/tag/" + url.PathEscape(tag.Name)），
      再 quote 一次会把 % 编成 %25，产出的链接形如
      https://opc.run/projects/tag/%25E5%25BC%2580%E5%258F%91... —— **双重编码 = 死链**
      （实测线上 categories 输出的全部 10 条"进入分类"链接都是这个形态）。
    ★ 先还原成字面量再统一编码，后端给裸中文 / 给已编码两种情况都得到同一结果。
    """
    parts = urllib.parse.urlsplit(str(raw))
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/"), parts.query, "",
    ))


def render_categories(data) -> str:
    items = _get(data, "items", [])
    if not items:
        return "暂未配置分类标签。"
    lines = ["### 热门分类（Top %d，按热度返回，非全量；完整清单见站内）" % len(items), "",
             "| 分类 | 项目数 | 站内入口 |", "|---|---|---|"]
    for item in items:
        name = _get(item, "name", "-")
        raw = _get(item, "url") or "%s/tag/%s" % (PROJECTS_URL, name)
        tag_url = client.with_source(_quote_tag_url(raw))
        lines.append(
            "| %s | %s | [进入分类](%s) |"
            % (name, _get(item, "project_count", "-"), tag_url)
        )
    lines.append("")
    lines.append("🔗 用 `--tag=<分类>`（分类名照抄第一列）检索该分类下的项目。")
    return "\n".join(lines) + _source_footer()


def render_usage(data, quota) -> str:
    stats = client.cache_stats()
    identity = _get(data, "identity_type", "")
    if not identity:
        identity = quota.identity or ""
    # 后端身份取值：匿名=ip（响应头 ip:{addr}）/ 带 Key=key（响应头 key:{id}）/ 已登录=user；
    # 历史曾用 "api_key"，这里一并兼容，避免把已配 Key 的用户误判成"匿名"
    is_registered = identity in ("key", "api_key", "user") or identity.startswith("key")
    if not identity:
        # 网络/服务失败拿不到身份头时（quota 降级分支），用本地事实兜底：
        # 配了 Key 的用户绝不能显示"匿名"并被推注册
        is_registered = bool(client.resolve_api_key())
    lines = ["### 配额使用情况", ""]
    lines.append("- 身份：%s" % ("已配置 API Key" if is_registered else "匿名（未配置 API Key）"))
    lines.append("- 额度：%s / %s 次（窗口：%s）"
                 % (_get(data, "remaining", "-"), _get(data, "limit", "-"), _get(data, "window", "day")))
    reset = _get(data, "reset_at", "") or quota.reset_at
    if reset:
        lines.append("- 重置时间：%s" % reset)
    plan = _get(data, "plan", "")
    if plan:
        # anonymous 是接口值，翻成用户能懂的说法（free / vip 本身就是站点层级名，保持原样）
        lines.append("- 套餐：%s" % ("匿名" if plan == "anonymous" else plan))
    lines.append("- 本地缓存：%d 条 / %.1f KB（命中缓存不消耗配额）" % (stats["count"], stats["bytes"] / 1024.0))
    lines.append("")
    if not is_registered:
        lines.append("🚀 匿名额度有限。[注册 OPC.run 免费领取 API Key](%s)，额度大幅提升。" % REGISTER_URL)
        lines.append("   已有账号？[在这里取 Key](%s)。" % API_KEYS_URL)
    else:
        lines.append("🔑 [管理你的 API Key](%s)" % API_KEYS_URL)
    return "\n".join(lines) + _source_footer()


def _truncate(text: str, length: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= length else text[: length - 1] + "…"


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def _json_stderr_notes(data) -> None:
    """
    --json 模式的 stderr 提示：stdout 保持纯 JSON，来源与合规提示走 stderr。

    ★ 要**下钻一层 items**：detail/quota 的字段在顶层，而 ranking / semantic
    的商业分和协议都在 data["items"] 列表里 —— 只查顶层的话列表类命令
    一条合规提示都出不来。
    """
    sys.stderr.write("来源：OPC.run 开源精选（%s），转载请保留 from=skill 来源参数\n"
                     % client.with_source(PROJECTS_URL))
    nodes = []
    if isinstance(data, dict):
        nodes.append(data)
        for value in data.values():
            if isinstance(value, list):
                nodes.extend(v for v in value if isinstance(v, dict))
    # AI_NOTE / LICENSE_NOTE 自带"注："前缀，别再拼一层
    if any(n.get("commercial_score") is not None for n in nodes):
        sys.stderr.write("%s\n" % client.AI_NOTE)
    if any(n.get("license") or n.get("license_risk") for n in nodes):
        sys.stderr.write("%s\n" % client.LICENSE_NOTE)


def _call(path, params, ttl, args, renderer):
    """统一执行：发起请求 -> 选择渲染器 -> 输出。"""
    if getattr(args, "no_cache", False):
        os.environ["OPCRUN_NO_CACHE"] = "1"
    result = client.get(
        path,
        params,
        ttl=0 if getattr(args, "no_cache", False) else ttl,
        refresh=getattr(args, "refresh", False),
        offline=getattr(args, "offline", False),
    )
    data = result["data"] or {}

    if getattr(args, "json", False):
        _json_stderr_notes(data)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(renderer(data))
    return 0


LIMIT_CAPS = {"semantic": 20, "ranking": 20}  # 与后端口径一致（api-contract §4.1/§4.2）
LIMIT_DEFAULTS = {"semantic": 10, "ranking": 20}


def _clamp_limit(args, endpoint: str) -> int:
    """
    客户端先收敛 limit，别把注定失败的请求发出去：
    服务端对 0 / 负数 / 超上限是**直接 400**（GoFrame 校验在 handler 之前，
    而配额中间件在更外层 —— 一次 400 也可能白扣配额）。
    收敛时打一行 stderr 提示，避免 Agent 拿到被钳制后的 N 条、却以为传的 100 生效了
    （提示里带上真实上限，见 LIMIT_CAPS）。
    """
    limit = getattr(args, "limit", 0)
    cap = LIMIT_CAPS[endpoint]
    if limit <= 0:
        # 0 / 负数同样是"注定 400"的请求，放行就是白扣配额；
        # 替它落回默认值并提示（stderr，不污染 stdout 的结构化输出）
        sys.stderr.write("提示：--limit 需为正整数（收到 %r），已改用默认值 %d\n"
                         % (limit, LIMIT_DEFAULTS[endpoint]))
        return LIMIT_DEFAULTS[endpoint]
    if limit > cap:
        sys.stderr.write("提示：%s 单次最多返回 %d 条，已按 %d 处理\n" % (endpoint, cap, cap))
        return cap
    return limit


def _warn_unknown_tag(tag: str) -> None:
    """
    用**本地缓存的**分类清单提前拦一道：--tag 拼错只会得到空结果 + 白烧配额
    （凭印象写"AI"这种分类名是不存在的）。只在有缓存时校验，
    没有缓存就静默跳过 —— 绝不为校验多花一次配额。

    ★ 走 client.cached（只读缓存，不联网、不走 client.get）：主调用可能带
    --no-cache / --refresh，那是"本次业务请求不要缓存"的意思，
    不该连坐校验用的这份只读缓存。

    ★ 这份缓存是**热门口径**，不是全量：实测后端每次只返回 10 条分类。
      所以命中不到时只能说"已缓存的 N 个里没有"，绝不能说成"共 N 个分类"
      —— 那会让传了真实冷门分类的用户以为自己写错了。
    """
    if not tag:
        return
    try:
        cached = client.cached("/skill/projects/categories", {"limit": 100}, TTL_STATIC)
        names = [str(c.get("name", "")) for c in ((cached or {}).get("items") or [])]
    except Exception:  # noqa: BLE001 - 校验失败不阻断主流程
        return
    if not names or tag in names:
        return
    close = difflib.get_close_matches(tag, names, n=3, cutoff=0.4)
    suggestion = "、".join(close) if close else "、".join(names[:5])
    # ★ 措辞必须留余地：清单只含热门分类（后端每次最多返回 10 条），
    #   所以它只能说明"缓存里没有"，不能断言"这个分类不存在 / 一定会空结果"。
    sys.stderr.write(
        "⚠️ 分类「%s」不在本地已缓存的 %d 个热门分类里（该清单不是全量）。最接近的：%s；"
        "若你确信这个分类存在，可忽略本提示继续检索。想看完整清单请运行 `categories`\n"
        % (tag, len(names), suggestion)
    )


def cmd_semantic(args) -> int:
    _warn_unknown_tag(getattr(args, "tag", ""))
    params = {"q": args.query, "tag": args.tag, "limit": _clamp_limit(args, "semantic")}
    return _call(
        "/skill/projects/semantic",
        params,
        TTL_SEARCH,
        args,
        lambda data: render_project_list(
            _get(data, "items", []),
            "语义检索：%s" % args.query,
        ),
    )


def cmd_ranking(args) -> int:
    _warn_unknown_tag(getattr(args, "tag", ""))
    params = {"sort": args.sort, "tag": args.tag, "limit": _clamp_limit(args, "ranking")}
    return _call("/skill/projects/ranking", params, TTL_RANKING, args,
                 lambda data: render_ranking(data, args))


def cmd_categories(args) -> int:
    # limit=100 是「尽力而为」：分类清单是 --tag 的合法值域，理论上给足就能拿全。
    # 但实测（2026-10）带 limit=100 时线上仍只返回 10 条，所以文档与渲染标题都按
    # 「热门分类 / 不是全量」口径表述，完整清单指向站内分类条。
    # 后端放开截断后，这里无需改动 —— 真拿到全量时标题会自动显示真实个数。
    # ★ 别忘了 _warn_unknown_tag 用的是同一份缓存：它因此**不能**断言
    #   "这个分类不存在"，只能说"缓存的热门分类里没有"（见那里的措辞）。
    return _call("/skill/projects/categories", {"limit": 100}, TTL_STATIC, args, render_categories)


def cmd_detail(args) -> int:
    return _call("/skill/projects/detail", {"slug": args.slug.strip("/")}, TTL_STATIC, args, render_detail)


def cmd_compare(args) -> int:
    """
    本地对比：逐个拉详情（命中缓存时零配额消耗），再拼成对比表。

    ★ 单个 slug 失败（404 / 网络错误）**不中断整体**：先把成功的渲染出来，
    失败的单独列出 —— 否则第二个 slug 404 就把第一个已花配额取到的结果全丢。
    ★ 注意首次对比 N 个 slug = N 次配额（命中缓存才免费）；匿名额度 3 次/天，
    建议一次别超过 2 个，或先逐个 `detail` 再 `compare`（那就全走缓存）。
    """
    if getattr(args, "no_cache", False):
        os.environ["OPCRUN_NO_CACHE"] = "1"
    items = []
    failed = []
    for slug in args.slugs:
        # 与 cmd_detail 走同一个 path + 同一份 params（slug），
        # 这样缓存键完全一致 —— 已经 detail 看过的项目，compare 时零消耗。
        try:
            result = client.get(
                "/skill/projects/detail",
                {"slug": slug.strip("/")},
                ttl=TTL_STATIC,
                refresh=getattr(args, "refresh", False),
                offline=getattr(args, "offline", False),
            )
        except client.ApiError as exc:
            sys.stderr.write("⚠️ %s 获取失败（%s），继续处理其余条目\n" % (slug, exc.message))
            failed.append(slug)
            continue
        item = result.get("data")
        if isinstance(item, dict) and item:
            items.append(item)
        else:
            failed.append(slug)
    # ★ JSON 分支必须排在"全失败"判定**之前**：--json 的调用方同样要拿到结构化结果，
    #   否则 stdout 空着、只剩一个退出码，它无从知道哪些 slug 失败了。
    #   退出码照旧（全失败 = 4，与 NotFoundError.exit_code 同源），成败语义不变。
    if getattr(args, "json", False):
        # compare 不走 _call，stderr 的来源/合规提示要自己补一份
        _json_stderr_notes({"items": items, "failed": failed})
        print(json.dumps({"items": items, "failed": failed}, ensure_ascii=False, indent=2))
        return client.NotFoundError.exit_code if not items else 0
    if not items:
        sys.stderr.write("所有条目都未取得数据（slug 有误或网络失败）。\n")
        return client.NotFoundError.exit_code
    print(render_compare(items, failed))
    return 0


def cmd_quota(args) -> int:
    """
    查询剩余配额。

    ★ 查询失败**不降级成一份看起来正常的配额**：否则打印出的"匿名/额度 - / -"
      与查询成功完全无法区分，Agent 会把"查不到"当成"还有额度"继续烧请求。
      失败就明确标注并返回退出码（5=网络异常），与 brainstorm 侧口径一致。
    """
    try:
        result = client.get("/skill/quota", {}, ttl=0, quota_log=False)
    except ApiError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": "配额查询失败", "detail": exc.message},
                             ensure_ascii=False, indent=2))
        else:
            print("❌ 配额查询失败：%s" % exc.message)
            print("")
            print("拿不到真实余额时不要假设还有额度 —— 联网检索前建议先重试一次。")
            print("本地缓存占用：%d 条 / %.1f KB（命中缓存不消耗配额）"
                  % (client.cache_stats()["count"], client.cache_stats()["bytes"] / 1024.0))
        return exc.exit_code
    data = result["data"] or {}
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(render_usage(data, result["quota"]))
    return 0


def cmd_auth(args) -> int:
    """
    API Key 的落盘入口：校验 → 保存 → 回显验证结果，一条命令做完。

    用法：
      auth <API_KEY>   校验并保存到本地文件（OPCRUN_HOME/api_key；POSIX 下设为 600 权限）
      auth --status    查看当前 Key 来源与身份（不落盘）
      auth --clear     删除本地保存的 Key

    为什么 Agent 不该自己写文件：保存路径受 OPCRUN_HOME 影响、要设 600 权限、
    还要先调 quota 验证 Key 有效 —— 这些都封装在这里，Agent 只需把用户给的
    Key 原样传进来。校验失败不会落盘，避免存下一个坏 Key。
    """
    if getattr(args, "clear", False):
        existed = client.KEY_FILE.exists()
        try:
            client.KEY_FILE.unlink(missing_ok=True)
        except OSError as exc:
            print("删除失败：%s" % exc)
            return 1
        if existed:
            print("已删除本地保存的 API Key（%s）。" % client.KEY_FILE)
            print("注意：环境变量 OPCRUN_API_KEY 若仍在设置，则会继续生效。")
        else:
            print("本地没有保存的 API Key（%s 不存在）。" % client.KEY_FILE)
        return 0

    env_key = (os.getenv("OPCRUN_API_KEY") or "").strip()
    if getattr(args, "status", False):
        if env_key:
            source, masked = "环境变量 OPCRUN_API_KEY", client.mask_key(env_key)
        else:
            key = client.resolve_api_key()
            if not key:
                print("当前未配置 API Key（匿名身份）。")
                # 无 Key 时恰恰最需要知道还剩几次：--status 也要查配额，
                # 否则文档承诺的"查看当前来源与额度"只兑现了一半
                try:
                    result = client.get("/skill/quota", {}, ttl=0, quota_log=False)
                    data = result.get("data") or {}
                    print("- 额度：%s / %s 次/天，重置时间 %s"
                          % (data.get("remaining", "-"), data.get("limit", "-"), data.get("reset_at", "-")))
                except ApiError as exc:
                    print("- 额度查询失败：%s" % exc.message)
                print("- 配置方式：运行 `%s`，或设置环境变量 OPCRUN_API_KEY。"
                      % client.cmd_line("projects.py", "auth <你的API_KEY>"))
                print("- 还没有 Key？[注册 OPC.run 免费领取](%s)。" % REGISTER_URL)
                return 0
            source, masked = "本地文件 %s" % client.KEY_FILE, client.mask_key(key)
        print("Key 来源：%s（%s）" % (source, masked))
        try:
            result = client.get("/skill/quota", {}, ttl=0, quota_log=False)
        except ApiError as exc:
            print("配额查询失败：%s" % exc.message)
            return exc.exit_code
        print(render_usage(result["data"] or {}, result["quota"]))
        return 0

    key = (getattr(args, "key", "") or "").strip()
    if not key:
        print("用法：%s（或 --status / --clear）" % client.cmd_line("projects.py", "auth <API_KEY>"))
        return 1

    # 先用新 Key 验证再落盘：把新 Key 挂到环境变量最前面（resolve_api_key 的第一优先级），
    # 不污染调用方自己的环境（用完即还原）
    os.environ["OPCRUN_API_KEY"] = key
    try:
        try:
            result = client.get("/skill/quota", {}, ttl=0, quota_log=False)
        except client.AuthError as exc:
            print("Key 校验失败，未保存：%s" % exc.message)
            print("请确认是否完整复制了 Key；也可以到 [API Keys 页面](%s) 重新生成。" % API_KEYS_URL)
            return exc.exit_code
        client.save_api_key(key)
        data = result["data"] or {}
        print("✅ API Key 已验证并保存到 %s（%s，脱敏显示：%s）"
                  % (client.KEY_FILE, client.key_perm_note(), client.mask_key(key)))
        # ★ 别写"已注册 if … else 已注册（免费层）"这种两支同义的条件 —— 那是死分支，
        #   无论走哪支都打印"已注册"，一个字的信息都没给到。如实打印套餐层级。
        print("- 套餐：%s" % ("免费层" if (data.get("plan") or "") in ("", "free") else data.get("plan")))
        print("- 额度：%s / %s 次/天，重置时间 %s"
              % (data.get("remaining", "-"), data.get("limit", "-"), data.get("reset_at", "-")))
        print("提示：环境变量 OPCRUN_API_KEY 的优先级高于此文件；若此前设置过它，建议移除以免新旧 Key 混用。")
        return 0
    finally:
        # 还原环境变量：校验用的新 Key 不该留在当前进程环境里
        if env_key:
            os.environ["OPCRUN_API_KEY"] = env_key
        else:
            os.environ.pop("OPCRUN_API_KEY", None)


def cmd_cache_clear(args) -> int:
    removed = client.clear_cache()
    print("已清空本地缓存：%d 条" % removed)
    return 0


def cmd_cache_list(args) -> int:
    stats = client.cache_stats()
    print("本地缓存目录：%s" % client.CACHE_DIR)
    print("条目数：%d ｜ 占用：%.1f KB" % (stats["count"], stats["bytes"] / 1024.0))
    print("（缓存用于节省配额：榜单 6 小时、检索 1 小时、项目详情与分类清单 24 小时）")
    return 0


# --------------------------------------------------------------------------
# CLI 装配
# --------------------------------------------------------------------------

class _SilentExitParser(argparse.ArgumentParser):
    """
    argparse 默认把用法错误以退出码 2 抛出，与「2 = API Key 无效」撞车，
    Agent 会把"参数写错了"误判成"Key 坏了去重新领"。统一改成 1（通用失败）。
    """

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("错误：%s\n" % message)
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = _SilentExitParser(
        prog="projects.py",
        description="OPC.run 开源精选检索 / 榜单 / 详情（0 依赖）",
    )
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("--json", action="store_true", help="输出原始 JSON")
        p.add_argument("--refresh", action="store_true", help="忽略缓存强制联网（消耗配额）")
        p.add_argument("--offline", action="store_true", help="只读本地缓存（不消耗配额）")
        p.add_argument("--no-cache", action="store_true", help="本次不读写缓存")

    # semantic（-> /projects/semantic）
    p = sub.add_parser("semantic", help="语义检索（自然语言需求 / 关键词 / 项目名）")
    # ★ help 必须同时说清两种用法：只写"用一句话描述"会让 Agent 以为关键词不能传，
    #   而"关键词 / 项目名同样命中"正是本 Skill 反复强调、最容易被误解的一点
    p.add_argument("query", help="用一句话描述需求，或直接给关键词 / 项目名（同一入口，都能命中）")
    p.add_argument("--tag", default="", help="限定分类，留空为全站")
    p.add_argument("--limit", type=int, default=10, help="返回条数，最大 20")
    add_common(p)
    p.set_defaults(func=cmd_semantic)

    # ranking（-> /projects/ranking）
    p = sub.add_parser("ranking", help="榜单：周增长 / 月增长 / 商业价值")
    p.add_argument(
        "--sort",
        default=DEFAULT_SORT,
        choices=list(SORT_LABELS.keys()),
        help="growth_7d=近 7 天 Star 增速（默认）｜ growth_30d=近 30 天增速 ｜ commercial=AI 六维商业分",
    )
    p.add_argument("--tag", default="", help="限定分类，留空为全站")
    p.add_argument("--limit", type=int, default=20, help="返回条数，最大 20")
    add_common(p)
    p.set_defaults(func=cmd_ranking)

    # categories
    p = sub.add_parser(
        "categories",
        help="热门分类与项目数（按热度返回，后端每次最多 10 条，非全量；完整清单见站内 projects 页分类条）",
    )
    add_common(p)
    p.set_defaults(func=cmd_categories)

    # detail（-> /projects/detail?slug=）
    p = sub.add_parser("detail", help="项目详情（摘要：Star/增长/协议/商业评分与置信度；六维明细与切入方向在站内详情页）")
    p.add_argument("slug", help="站内 slug，形如 owner-repo")
    add_common(p)
    p.set_defaults(func=cmd_detail)

    # compare（本地组合，复用 detail 的接口与缓存）
    p = sub.add_parser("compare", help="多项目横向对比（选品决策）")
    p.add_argument("slugs", nargs="+")
    add_common(p)
    p.set_defaults(func=cmd_compare)

    # quota（-> /skill/quota，注意不在 /projects 命名空间下）
    # ★ 不继承 add_common：quota 恒 ttl=0 且每次联网，--offline / --refresh /
    #   --no-cache 对它全是空操作。注册了却做不到，比不注册更容易误导。
    p = sub.add_parser("quota", help="查看剩余配额")
    p.add_argument("--json", action="store_true", help="输出原始 JSON（供二次加工）")
    p.set_defaults(func=cmd_quota)

    # auth（纯本地命令，无 API：校验 + 落盘 API Key）
    p = sub.add_parser("auth", help="配置 API Key：校验并保存（auth <KEY>），或查看/清除（--status / --clear）")
    p.add_argument("key", nargs="?", default="", help="API Key，形如 sk_xxxx（从 opc.run/app/profile/api-keys 获取）")
    p.add_argument("--status", action="store_true", help="查看当前 Key 来源与配额（不修改任何东西）")
    p.add_argument("--clear", action="store_true", help="删除本地保存的 Key")
    p.set_defaults(func=cmd_auth)

    # cache 管理
    p = sub.add_parser("cache-clear", help="清空本地缓存")
    p.set_defaults(func=cmd_cache_clear)
    p = sub.add_parser("cache-list", help="查看本地缓存占用")
    p.set_defaults(func=cmd_cache_list)

    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except client.QuotaExceeded as exc:
        # ★ 引导按身份分流：给匿名用户推注册是转化点，给已注册用户推注册只会让人困惑。
        # 注册链接优先用后端 429 data 里的（与站内口径同步），客户端常量兜底
        print(exc.message)
        print("")
        if exc.is_anonymous:
            print("🚀 [注册 OPC.run 即可领取免费 API Key](%s)（注册后自动回到领 Key 页面）。"
                  % (exc.register_url or REGISTER_URL))
            print("")
            print("拿到 Key 后按下面三步开启更高额度：")
            print("  1. %s   # 校验并保存到本地（%s）"
                  % (client.cmd_line("projects.py", "auth <你的API_KEY>"), client.key_perm_note()))
            print("  2. %s               # 验证额度已生效" % client.cmd_line("projects.py", "quota"))
            print("  3. 之后正常使用即可，无需每次传 Key")
            print("     （也可以设环境变量 OPCRUN_API_KEY，其优先级高于本地文件）")
        else:
            print("额度将于 %s 重置。" % (exc.reset_at or "明日 0 点（Asia/Shanghai）"))
            print("💡 本地缓存的内容仍可离线查看：给命令加 --offline 参数，不消耗额度。")
        return exc.exit_code
    except client.AuthError as exc:
        print(exc.message)
        print("")
        print("🔑 到 [API Keys 页面](%s) 重新生成后，运行 `%s` 保存。"
              % (API_KEYS_URL, client.cmd_line("projects.py", "auth <新Key>")))
        return exc.exit_code
    except client.NotFoundError as exc:
        print(exc.message)
        print("")
        print("🔗 可在 [站内开源精选](%s) 浏览全部收录项目，确认正确的 slug。"
              % client.with_source(PROJECTS_URL))
        return exc.exit_code
    except client.NetworkError as exc:
        print(exc.message)
        return exc.exit_code
    except ApiError as exc:
        print(exc.message)
        if exc.hint:
            print(exc.hint)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
