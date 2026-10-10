#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc-run-super-brainstorm / scripts / brainstorm.py

统一命令行入口：把 OPC.run「超级智囊团」暴露成若干子命令。

    python3 scripts/brainstorm.py ask     <你的问题> [--rounds=2] [--no-wait]   -> POST /skill/board/ask
    python3 scripts/brainstorm.py task    <task_id>                             -> GET  /skill/board/task
    python3 scripts/brainstorm.py mentors                                       -> GET  /skill/board/mentors
    python3 scripts/brainstorm.py quota                                         -> GET  /skill/quota
    python3 scripts/brainstorm.py auth    <API_KEY> [--status] [--clear]        -> 本地命令，无 API

通用参数：
    --json        输出原始 JSON（供 Agent 自行加工），默认输出 Markdown
    --no-cache    本次请求不读不写缓存
    --offline     只读本地缓存（零配额消耗，仅 task / mentors 支持）

退出码：
    0 成功  1 通用失败  2 API Key 无效  3 配额耗尽  4 未找到  5 网络异常
    6 点数不足 / 账户冻结（仅配置 API Key 后可能出现）  130 用户 Ctrl-C 中断
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opc_client as client  # noqa: E402
from opc_client import (  # noqa: E402
    API_KEYS_URL,
    AI_NOTE,
    INTRO_URL,
    POINTS_URL,
    REGISTER_URL,
    TTL_DISCUSSION,
    TTL_MENTORS,
    WORKSPACE_URL,
    ApiError,
    NetworkError,
)

# 议题长度：与后端 req.SkillBoardAskReq 的 v:"length:10,1000" 一致。
# ★ 客户端先校验一次：长度不合法的请求注定 400，而配额在更外层已经计过了，
#   放过去就是"什么都没拿到还白扣一次"
TOPIC_MIN_RUNES = 10
TOPIC_MAX_RUNES = 1000

ROUNDS_MIN = 1
ROUNDS_MAX = 3
ROUNDS_DEFAULT = 2

MENTORS_LIMIT_DEFAULT = 20
MENTORS_LIMIT_MAX = 50

# 轮询间隔（分段）：前 30 秒 5 秒一次，之后 3 秒一次
# ★ 分段理由：每位导师发言约 25~30s（串行 LLM 调用），开始 30 秒内下一条发言
#   大概率还没落库，5 秒一次足够；过了 30 秒进入"随时可能出下一条"的窗口，
#   加密到 3 秒，让新发言尽快浮出来。轮询不消耗配额，加密只为体验不为省钱。
POLL_INTERVAL_SLOW = 5    # 开始 30 秒内：当前导师还在生成，快轮询是白跑
POLL_INTERVAL_FAST = 3    # 30 秒后：下一条随时可能落库
POLL_FAST_AFTER = 30      # 切换点（秒，从轮询启动算起）

# ★ 超时判定是「**连续多久没有新发言**」，不是「总共等多久」。
#   原因：讨论是串行 LLM 调用（导师要听着前面的人接话），导师越多越慢 ——
#   实测每次发言约 25~30s。3 位×2 轮约 3 分钟，5 位×3 轮约 8 分钟。
#   固定总时长（比如原来的 300s）在阵容变大后必然中途退出，用户得手动 task 续查 ——
#   而发言是增量打印的，中途退出等于把最慢的那场讨论截断在用户眼前。
#   按"无进展时长"判定更贴合实际：只要还在出发言就继续等，3 位和 5 位都能自然跑完。
IDLE_TIMEOUT_DEFAULT = 120
# 兜底硬上限：防止"一直有零星进展但永远不结束"把用户无限期挂住
TOTAL_TIMEOUT_HARD = 1800
# 等待下限：至少要够跑完 1 次发言（1 位导师约 20~40s），否则秒退体验很差
POLL_MIN_TIMEOUT = 30

STATUS_LABELS = {
    "pending": "排队中",
    "running": "讨论中",
    "completed": "已完成",
    "failed": "失败",
}


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


def _truncate(text: str, length: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= length else text[: length - 1] + "…"


def _mentor_label(item) -> str:
    """导师展示名：称号优先，没有称号退回 slug。"""
    return _get(item, "mentor_title") or _get(item, "title") or _get(item, "slug", "导师")


def _source_footer(note: str = "") -> str:
    """
    结尾来源行。**Agent 必须原样保留**。

    默认不塞免责长文（那是 Skill 详情页与站内条款页的职责）；
    部署方如需每条都带，设环境变量 OPCRUN_LEGAL_FOOTER=1。
    """
    head = "数据来源：OPC.run 超级智囊团 · [opc.run/session](%s)" % INTRO_URL
    if note:
        head = "%s ｜ %s" % (note, head)
    if client.legal_footer_enabled():
        return "\n\n---\n%s\n⚠️ %s\n" % (head, client.DISCLAIMER_SHORT)
    return "\n\n---\n%s\n" % head


def _guide_line(data) -> str:
    """
    结尾的站内引导。**每条讨论结果都要有这一段** —— 这是 Skill 的转化口。

    ★ 措辞纪律（别用内部黑话，用户看不懂）：
      -「收口」「圆桌决议」→ 说「结论」。用户只关心"有没有一个明确的答案"。
      -「跑完」→ 说「说完」。机器味太重。
      -「接入」「接进账号」→ 直接说**用户要做的那件事**（「登录后接着聊」）。
      -「Skill 侧 / Skill 这边没法答」→ 说「我这边」。这段话是 Agent 对用户说的，
        视角是"我"，不是"某个叫 Skill 的东西"。
      ★ 内部术语不是"专业"，是没解释的缩写。用户读到「收口」只会困惑，不会觉得高级。

    ★ 链接一律用 Markdown 超链接：可见文字很短、URL 藏在链接目标里，
      对话界面渲染出来只有一小段可点文字，不会把一整串地址甩到用户脸上。
    ★ 「有没有 Key」分支仍只看本地（resolve_api_key）；认领链接要看服务端的 claim_url。
    """
    web_url = client.with_source(_get(data, "web_url") or WORKSPACE_URL)
    asked = _asked_count(data)

    if asked:
        # ★ 有导师问过用户时，开头就点这件事 —— 它是用户此刻唯一想做的事，
        #   早于"没有结论"这个抽象的产品设定。
        lines = [
            "💬 **有 %d 位导师问了你问题**（上面标了 ❓ 的那几条）—— "
            "这些问题得你来回答，我这边没法替你回答。" % asked,
        ]
    else:
        lines = []

    lines.append(
        "💡 **讨论说完了，但还没有一个结论** —— 导师们各抒己见，"
        "谁也没给出一个决定性的建议。想要明确的答案、或者想接着聊，都要去站内。")

    if asked:
        lines.append("⚠️ Skill 版最多 3 轮，说完就停 —— 不会中途停下来等你回答。")

    lines.append(
        "🚀 [去 OPC.run 站内](%s) 能多做一些：导师更多、轮次不限，"
        "**你可以随时插话**，导师会停下来等你回答。" % web_url)

    if client.resolve_api_key():
        lines.append(
            "👉 **[打开这场讨论](%s)** —— 它已经在你的智囊团里了%s。"
            % (web_url, ("，导师问你的那 %d 个问题也在" % asked) if asked else ""))
    else:
        lines.extend(_claim_lines(data, asked))

    lines.append("🔗 还不了解超级智囊团？[看看它能做什么](%s)" % INTRO_URL)
    return "\n".join(lines)


def _claim_lines(data, asked=0) -> list:
    """
    匿名讨论的认领引导。

    ★ 这是匿名用户**唯一**能接回这场讨论的路，必须给，而且要放在最显眼的位置：
      匿名讨论落在 AI 问答记录里，站内打开一场讨论读的是另一套数据，
      没有这条链接他注册登录后也找不到这场讨论（后端 boardService/claim.go）。

    ★ 认领链接本身就是"登录后接着讨论"的入口，**不与注册登录耦合**：
      未登录点它会被站内守卫带 return_url 送去登录页，登录完自动弹回。
      所以话术是"打开链接"而不是"先注册再回来"—— 后者会让人以为要重新走一遍。

    ★ 链接文字写**用户要做的那件事**（「登录后接着聊这场讨论」），
      不写机制（「把这场讨论接进你的账号」）—— 用户不关心它存哪，只关心点开能干什么。

    ★ 三态（再加一态"确认被别人认领"）：
      - 有 claim_url → 给链接（这是刚提交的那场，或还没被认领的旧场）
      - claimed_by_other → **确认**是别人的账号，别再给链接（点了只会看到拒绝）
      - claimed → 已认领（多数是本人刚点过链接），别再给链接
      - 都没有→ 老服务端 / 异常，兜底给注册引导，不让引导段落空掉

    ★ claimed 用"你的"而不是"某个账号"：Skill 匿名请求不带登录态，
      服务端**无从核实**认领者是不是本人（claimed_by_other 只在确定不是时才 true）。
      现实中绝大多数就是本人刚点过认领链接 —— 说"某个账号"会让用户以为讨论归了陌生人，
      反而不知道该不该去找。真的不是本人时，claimed_by_other 会把话说清楚。

    ★ asked 带上提问数：这是匿名用户**唯一**的行动理由。说他"这场讨论归你了"
    不如说"这 %d 个问题在等你答" —— 后者才是他此刻真正想做的事。
    """
    tail = ("，导师问你的那 %d 个问题也在里面" % asked) if asked else ""

    # ★ 顺序：**先判“确认被别人认领”，再给链接**。
    if _get(data, "claimed_by_other"):
        return ["🔗 这场讨论**已被另一个账号认领**（认领链接可能被转发过）。"
                "去站内登录你自己的账号，在工作台里找找有没有这场讨论。"]
    if _get(data, "claimed"):
        return ["🔗 这场讨论已经存到你的账号里了%s，去站内工作台就能看到。" % tail]

    claim_url = _get(data, "claim_url")
    if claim_url:
        return [
            "🔗 **[登录后接着聊这场讨论](%s)** —— 登录完会自动回到这场%s。"
            % (client.with_source(claim_url), tail),
        ]

    return [
        "🔑 或者 [注册并领取免费 API Key](%s)：额度更高，讨论还能跟着你的账号走。"
        % REGISTER_URL
    ]


# --------------------------------------------------------------------------
# Markdown 渲染
# --------------------------------------------------------------------------

def render_ask_pending(data, task_id) -> str:
    """提交成功但不等结果时的输出（--no-wait）。"""
    lines = [
        "### 已提交给超级智囊团",
        "",
        "- 任务 ID：**%s**" % task_id,
        "- 议题：%s" % _get(data, "topic"),
        "- 轮数：%s ｜ 状态：%s" % (_get(data, "rounds", "-"), STATUS_LABELS.get("pending")),
        "",
        "稍后用下面这条命令取结果：",
        "",
        "```",
        client.cmd_line("brainstorm.py", "task %s" % task_id),
        "```",
    ]
    return "\n".join(lines) + _source_footer()


def render_header(data) -> str:
    """头部：会议名 + 议题 + 出席导师（增量输出时先打这一段）。"""
    name = _get(data, "name") or _get(data, "topic")
    if not name:
        # data 为空/字段缺失时不要输出 "### 超级智囊团 · " + "**议题**：" 的空壳 ——
        # 那看起来像"讨论跑完了但什么都没有"，比明确报错更让人困惑
        return "### 超级智囊团\n\n⚠️ 服务端没有返回这场讨论的内容（任务 ID：%s）。\n" % _get(data, "id", "—")
    lines = ["### 超级智囊团 · %s" % _truncate(name, 40), ""]
    lines.append("**议题**：%s" % _get(data, "topic"))
    lines.append("")

    mentors = _get(data, "mentors", []) or []
    if mentors:
        labels = []
        for item in mentors:
            title = _get(item, "title")
            full_name = _get(item, "full_name")
            if title and full_name:
                labels.append("%s（%s）" % (title, full_name))
            else:
                labels.append(title or full_name or _get(item, "slug"))
        lines.append("👥 **出席导师**：%s" % " ｜ ".join(labels))
        lines.append("")
    return "\n".join(lines)


def render_message(msg, prev_round) -> str:
    """
    单条发言。轮次变化时自动带一个「第 N 轮」小标题。

    ★ 传入上一条的 round（首条传 None），由它决定要不要插轮次标题 ——
      增量输出时每条是单独打印的，没法回头看全局。
    """
    round_no = msg.get("round") or 0
    out = []
    if round_no != prev_round:
        out.append("")
        out.append("#### 第 %s 轮" % round_no)
        out.append("")
    speaker = _mentor_label(msg)
    action = _get(msg, "action")
    head = "**%s**" % speaker
    if action:
        head += " *( %s )*" % action
    out.append(head)
    out.append("")
    out.append(_get(msg, "content"))
    out.append("")
    if msg.get("wait_for_user"):
            # ★ 直接用服务端给的 wait_for_user，**不要自己从内容里猜**：
            #   那是 LLM 生成时的结构化自述 + 服务端问句二次校验，猜不出来
            #   （修辞反问会被误判）。每条都标出来，用户才知道哪几条欠着他回答。
            out.append("> ❓ **%s 在等你回答** —— 这个问题得你来答。" % speaker)
            out.append("")
    return "\n".join(out)


def _asked_count(data) -> int:
    """本场有多少条发言在向用户提问。"""
    return len([m for m in (_get(data, "messages", []) or []) if m.get("wait_for_user")])


def render_tail(data) -> str:
    """
    尾部：AI 提示 + 站内引导 + 来源行。

    ★ task_id 必须打出来：SKILL.md 要求 Agent「回看结果用 `task <id>`、别重复 ask」，
      正常完成时若不给出这个 id，Agent 根本没法回看（只能重新提交，白烧一次额度）。

    ★ failed 走**完全不同的尾部**：不给「讨论说完了/ 还没有结论 / 去站内接着聊」那套引导。
      失败的场次没有结论可展示，引导用户去站内继续看一场不存在的讨论是纯粹的误导。
    """
    lines = []
    task_id = _get(data, "id")
    if task_id:
        lines.append("**任务 ID**：`%s` ｜ 回看：`%s`"
                 % (task_id, client.cmd_line("brainstorm.py", "task %s" % task_id)))
        lines.append("")

    if _get(data, "status") == "failed":
        # 只说事实 + 下一步。刻意不复述任何导师发言 —— 那是中途产物，
        # 复述它等于让用户以为这场讨论有结论
        lines.append("_这场讨论没有跑完，没有产出可用内容。_")
        lines.append("")
        lines.append("可以换个说法、把背景写得更具体一点再提交一次"
                     "（例如把身份、现状和具体决策点写进去）。")
        return "\n".join(lines) + _source_footer()

    # ★ 讨论"跑完了"不等于"每位导师都发言了"：服务端对单个导师的失败是静默跳过的，
    #   所以实际条数可能少于 expected。
    #   ★措辞刻意写得平静：用户已经拿到可用内容，再加一个"⚠️ 不完整"的大字告警
    #     只会让人怀疑剩下的发言也不可信 —— 那是纯粹的体验倒退。
    #     只陈述事实 + 说明剩下的能用，不渲染成故障。
    expected = data.get("expected") or 0
    got = len(_get(data, "messages", []) or [])
    if _get(data, "status") == "completed" and expected and got < expected:
        lines.append("_本场有 %d 位导师未能发言（AI 响应异常），其余发言可正常参考。_"
                     % (expected - got))
        lines.append("")

    if _get(data, "messages"):
        lines.append(AI_NOTE)
        lines.append("")
    lines.append(_guide_line(data))
    return "\n".join(lines) + _source_footer()


def render_timeout_tail(data, task_id) -> str:
    """
    超时（讨论仍在服务端跑）时的尾部。

    ★ 刻意**不给**"讨论说完了但还没有结论 / 不会中途停下来等你回答"那套引导 ——
      讨论还没结束，说这些是假的。等 `task` 拿到最终结果时再给。
    """
    got = len(_get(data, "messages", []) or [])
    expected = _get(data, "expected", 0)
    return "\n".join([
        "",
        "---",
        "",
        "⏳ 讨论还在继续（已产出 %d/%s 条发言）。剩下的部分稍后接着看，**不消耗额度**："
        % (got, expected or "?"),
        "",
        "```",
        client.cmd_line("brainstorm.py", "task %s" % task_id),
        "```",
    ]) + "\n"


def render_discussion(data) -> str:
    """
    整场讨论一次性渲染（会议头 + 全部发言 + 尾部）。

    ★ 顺序严格按 messages 数组（服务端已按 seq 升序返回），不要自己重排 ——
      导师是互相点名接话的，顺序本身就是讨论的脉络。
    """
    lines = [render_header(data)]
    messages = _get(data, "messages", []) or []
    if not messages:
        lines.append("_（暂时还没有发言记录，可能讨论还没开始或被中断了。）_")
        lines.append("")
    prev_round = None
    for msg in messages:
        lines.append(render_message(msg, prev_round))
        prev_round = msg.get("round") or 0
    lines.append(render_tail(data))
    return "\n".join(lines)


def render_mentors(data) -> str:
    items = _get(data, "items", []) or []
    if not items:
        return "暂时没有取到智囊团成员清单。"
    lines = ["### 超级智囊团成员（%d 位）" % len(items), ""]
    lines.append("| 称号 | 姓名 | 一句话简介 |")
    lines.append("|---|---|---|")
    for item in items:
        lines.append(
            "| %s | %s | %s |"
            % (
                _get(item, "title", "-"),
                _get(item, "full_name", "-"),
                _truncate(_get(item, "summary", "—"), 60),
            )
        )
    lines.append("")
    lines.append("🔗 [看看他们怎么开会](%s)" % INTRO_URL)
    return "\n".join(lines) + _source_footer()


def render_usage(data, quota) -> str:
    identity = _get(data, "identity_type", "")
    if not identity:
        identity = quota.identity or ""
    # 后端身份取值：匿名=ip / 带 Key=key / 已登录=user；历史曾用 "api_key"，一并兼容
    is_registered = identity in ("key", "api_key", "user") or identity.startswith("key")
    if not identity:
        # 拿不到身份头时用本地事实兜底：配了 Key 的用户绝不能显示"匿名"
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
        lines.append("- 套餐：%s" % ("匿名" if plan == "anonymous" else plan))
    stats = client.cache_stats()
    lines.append("- 本地缓存：%d 条 / %.1f KB（命中的讨论结果不消耗配额）"
                 % (stats["count"], stats["bytes"] / 1024.0))
    lines.append("")
    if not is_registered:
        lines.append("🚀 匿名额度有限。[注册 OPC.run 免费领取 API Key](%s)，额度大幅提升。" % REGISTER_URL)
        lines.append("   已有账号？[在这里取 Key](%s)。" % API_KEYS_URL)
    else:
        lines.append("🔑 [管理你的 API Key](%s)" % API_KEYS_URL)
    return "\n".join(lines) + _source_footer()


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def _json_stderr_notes(data) -> None:
    """--json 模式的 stderr 提示：stdout 保持纯 JSON，来源与免责提示走 stderr。"""
    sys.stderr.write("来源：OPC.run 超级智囊团（%s），转载请保留 from=skill 来源参数\n" % INTRO_URL)
    if isinstance(data, dict) and data.get("messages"):
        sys.stderr.write("%s\n" % AI_NOTE)


def _validate_topic(topic: str) -> str:
    topic = (topic or "").strip()
    length = len(topic)
    if length < TOPIC_MIN_RUNES:
        raise ApiError(
            "议题太短了（%d 字，至少 %d 字）。"
            "把背景和目标写进去，导师才能组得起来 —— 例如"
            "「我是一个人做跨境电商的卖家，月流水 3 万，该不该现在招第一个人？」"
            % (length, TOPIC_MIN_RUNES)
        )
    if length > TOPIC_MAX_RUNES:
        raise ApiError("议题太长（%d 字，最多 %d 字），请精简后再提交。" % (length, TOPIC_MAX_RUNES))
    return topic


def _clamp_rounds(rounds) -> int:
    """
    把 --rounds 收敛到 [ROUNDS_MIN, ROUNDS_MAX]。

    ★ 越界时**打一行stderr 提示**再回落：用户明确要 5 轮却拿到 2 轮，
      不提示就等于悄悄改了用户的参数（同一段代码里"提示里的等待时间必须与真实一致"的
      原则在这里同样适用）。
    """
    try:
        value = int(rounds)
    except (TypeError, ValueError):
        sys.stderr.write("提示：--rounds 需要整数，已按默认 %d 轮提交\n" % ROUNDS_DEFAULT)
        return ROUNDS_DEFAULT
    if value < ROUNDS_MIN or value > ROUNDS_MAX:
        sys.stderr.write("提示：--rounds=%d 超出范围（%d~%d），已按 %d 轮提交\n"
                         % (value, ROUNDS_MIN, ROUNDS_MAX, ROUNDS_DEFAULT))
        return ROUNDS_DEFAULT
    return value


def cmd_ask(args) -> int:
    """
    提交议题（消耗 1 次额度），默认**边讨论边输出**：
    一位导师说完就立刻打到 stdout，不用等整场结束。

    ★ 服务端是增量落库的（说一条存一条），这里靠"已打印到第几条"做增量，
      已输出的内容不会重复打印；全部发言吐完后补上 AI 提示 + 站内引导
      （★ 没有决议 —— Skill 只给讨论，结论在站内）。
    """
    if getattr(args, "no_cache", False):
        os.environ["OPCRUN_NO_CACHE"] = "1"

    # ★ ask 一定会联网（提交就是一次写操作 + 扣 1 次额度），所以 --offline 在这里是
    #   **语义错误**：原来 argparse 给 ask 也注册了 --offline，cmd_ask 又不处理，
    #   结果用户以为零消耗，实际照常提交并扣了额度。宁可明确拒绝，也不能静默烧额度。
    if getattr(args, "offline", False):
        raise ApiError(
            "提交议题（ask）必须联网，不能用 --offline：\n"
            "   提交是一次写操作，并且会消耗 1 次每日额度。\n"
            "   --offline 只适用于 `task`（查看已有讨论）和 `mentors`（成员名录）。"
        )

    topic = _validate_topic(args.topic)
    rounds = _clamp_rounds(args.rounds)

    result = client.post("/skill/board/ask", {"topic": topic, "rounds": rounds})
    data = result["data"] or {}
    task_id = data.get("task_id")
    if not task_id:
        raise ApiError("提交失败：服务端没有返回任务 ID。")

    if getattr(args, "no_wait", False):
        if getattr(args, "json", False):
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(render_ask_pending(data, task_id))
        return 0

    params = {"id": str(task_id)}
    as_json = getattr(args, "json", False)

    # ★ 缓存键统一用字符串：ask 拿到的 task_id 是 JSON int，task 子命令拿到的是命令行 str，
    #   不归一化的话两者算出的缓存键不同 —— ask 回写的缓存 task 永远读不到
    timeout = getattr(args, "timeout", IDLE_TIMEOUT_DEFAULT) or IDLE_TIMEOUT_DEFAULT
    if timeout < POLL_MIN_TIMEOUT:
        # 下限兜底，但**用实际生效的值**：否则提示里写"已等 N 秒"与真实等待时间不符；
        # 同时打一行提示，别让用户以为自己的 --timeout 被照办了
        sys.stderr.write("提示：--timeout=%d 秒低于下限，已按 %d 秒执行\n"
                         % (timeout, POLL_MIN_TIMEOUT))
        timeout = POLL_MIN_TIMEOUT

    hard_deadline = time.time() + TOTAL_TIMEOUT_HARD
    started_at = time.time()
    last_progress_at = started_at
    last_got = 0
    printed = 0          # 已渲染到第几条发言
    got = 0              # 服务端已产出的条数（--json 模式下 printed 不递增，靠它报进度）
    prev_round = None    # 上一条的轮次（决定是否插「第 N 轮」标题）
    header_done = False
    final = None

    while True:
        result = client.get("/skill/board/task", params, ttl=0, quota_log=False)
        data = result["data"] or {}
        status = _get(data, "status", "")
        messages = _get(data, "messages", []) or []
        got = len(messages)

        # ★ 每多一条发言就重新计时：等待上限按"无进展时长"算，不是总时长。
        #   5 位导师 × 3 轮是 15 次串行 LLM 调用（实测每次约 25~30s），
        #   用固定总时长必然会在最慢的那场讨论中途退出，把发言截断在用户眼前。
        if got > last_got:
            last_got = got
            last_progress_at = time.time()

        if not as_json:
            # 组好局（有会议名/导师）就先把头打出来，用户立刻知道谁在场
            if not header_done and (_get(data, "name") or _get(data, "mentors")):
                print(render_header(data))
                sys.stdout.flush()
                header_done = True

            if got > printed:
                for msg in messages[printed:]:
                    print(render_message(msg, prev_round))
                    prev_round = msg.get("round") or 0
                printed = got
                # ★ 立刻 flush：能流式读 stdout 的调用方（管道 / 终端）马上就看到
                sys.stdout.flush()

        if status in ("completed", "failed"):
            final = data
            break
        now = time.time()
        if now - last_progress_at >= timeout or now >= hard_deadline:
            break

        expected = data.get("expected") or 0
        if expected:
            # ★ 用 got 而不是 printed：--json 模式下不渲染，printed 恒为 0，
            #   进度条会一直显示"已收到 0/N 条"
            sys.stderr.write("⏳ 已收到 %d/%d 条发言…\n" % (got, expected))
        else:
            # expected=0 = 还没组好局，这时报"0/? 条"像坏了
            sys.stderr.write("⏳ 正在组局（挑选导师）…\n")
        # 分段间隔：按轮询已进行时长切换，不是按"距上一条发言"（那是 idle 超时的口径）
        elapsed = now - started_at
        time.sleep(POLL_INTERVAL_FAST if elapsed >= POLL_FAST_AFTER else POLL_INTERVAL_SLOW)

    if final is None:
        # 超时：讨论仍在服务端跑。★ 这里**必须照样输出**（哪怕 --json）——
        #   否则 stdout 空着，调用方既拿不到 task_id 也拿不到已产出的发言，
        #   这场讨论就等于"消失"了，用户没法接着看。
        pending = dict(data or {})
        pending["id"] = pending.get("id") or task_id
        pending["status"] = _get(pending, "status", "running")

        if as_json:
            _json_stderr_notes(pending)
            print(json.dumps(pending, ensure_ascii=False, indent=2))
            sys.stderr.write("⏳ 讨论尚未结束，用 `task %s` 接着看（不消耗额度）\n" % task_id)
            return 0

        if not header_done:
            print(render_header(pending))
        print(render_timeout_tail(pending, task_id))
        # ★ 说清是"多久没进展"而不是"等够了"：用户看到"已等 2450 秒"会以为坏了，
        #   实际是讨论一直在产出、只是还没结束
        sys.stderr.write("⏳ 讨论尚未结束（已等 %.0f 秒，期间一直在产出新的发言）\n"
                         % (time.time() - started_at))
        return 0

    # ★ failed 必须**先渲染再返回非零退出码**，且要放在 --json 分支**之前**：
    #   原来 failed 走完 render_tail 仍然 return 0，Agent 按退出码会把失败当成功，
    #   并向用户复述一场根本不存在的讨论（导师发言是讨论中途的，不等于这场讨论有结果）。
    #   JSON 模式同样要拿到非零码，否则 --json 的调用方也会误判。
    failed = _get(final, "status") == "failed"

    if not failed and _get(final, "status") == "completed":
        client.remember("/skill/board/task", params, final)

    if as_json:
        _json_stderr_notes(final)
        print(json.dumps(final, ensure_ascii=False, indent=2))
    else:
        if not header_done:
            print(render_header(final))
        print(render_tail(final))

    if failed:
        reason = _get(final, "error", "未知原因")
        sys.stderr.write("❌ 讨论失败：%s\n" % reason)
        sys.stderr.write("   这场讨论没有产出任何内容，不要向用户复述它的发言；"
                         "换个说法重新提交一次，或用 task %s 复查。\n" % task_id)
        return 1
    return 0


def cmd_task(args) -> int:
    """
    查询一场讨论的结果（不消耗额度）。

    ★ 只对 **completed** 的结果走缓存：讨论是增量落库的，进行中的响应会继续变长，
      把它缓存下来等于把半场讨论冻住 24 小时 —— 所以这里先读缓存、命中且已完成才用，
      否则一律联网，联网后也只有已完成才回写。
    """
    if getattr(args, "no_cache", False):
        os.environ["OPCRUN_NO_CACHE"] = "1"

    # 与 ask 回写缓存时用的键保持一致（见 cmd_ask）
    params = {"id": str(args.task_id)}
    use_cache = not getattr(args, "no_cache", False) and not getattr(args, "refresh", False)

    data = None
    if use_cache:
        hit = client.cached("/skill/board/task", params, TTL_DISCUSSION)
        if isinstance(hit, dict) and _get(hit, "status") == "completed":
            data = hit
            client.log("📦 命中本地缓存，本次不消耗配额")
    if data is None:
        if getattr(args, "offline", False):
            raise NetworkError(
                "离线模式下没有这场讨论的已完成缓存。"
                "进行中的讨论必须联网才能看到最新发言，请去掉 --offline。"
            )
        result = client.get("/skill/board/task", params, ttl=0)
        data = result["data"] or {}
        if use_cache and _get(data, "status") == "completed":
            client.remember("/skill/board/task", params, data)

    # ★ 讨论失败必须用非零退出码：Agent 靠退出码判断成败，
    #   原来 failed 也返回 0，Agent 会把失败当成功继续往下走。
    #   放在 --json 分支**之前**：JSON 模式同样要拿到非零码。
    if _get(data, "status", "") == "failed":
        reason = _get(data, "error", "未知原因")
        sys.stderr.write("❌ 讨论失败：%s\n" % reason)
        if getattr(args, "json", False):
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("❌ 讨论失败：%s" % reason)
            print("")
            print("这场没有产出任何内容。换个说法重新提交一次试试。")
        return 1

    if getattr(args, "json", False):
        _json_stderr_notes(data)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    status = _get(data, "status", "")
    if status == "completed":
        print(render_discussion(data))
        return 0

    # 未结束：把**已经产出的发言**照样打出来（服务端是增量落库的），末尾补进度
    lines = [render_header(data)]
    messages = _get(data, "messages", []) or []
    prev_round = None
    for msg in messages:
        lines.append(render_message(msg, prev_round))
        prev_round = msg.get("round") or 0

    label = STATUS_LABELS.get(status, status or "未知")
    expected = data.get("expected") or 0
    lines.append("---")
    lines.append("")
    if expected == 0:
        # expected=0 = 导师还没推荐出来（还没组好局），说"已产出 0/0 条"会让人以为坏了
        lines.append("**%s**：正在挑选导师、组局中…（任务 ID：%s，提交于 %s）"
                     % (label, args.task_id, _get(data, "created_at", "—")))
    else:
        lines.append("**%s**：已产出 %d/%d 条发言（任务 ID：%s，提交于 %s）"
                     % (label, len(messages), expected, args.task_id,
                        _get(data, "created_at", "—")))
    if _get(data, "error"):
        lines.append("")
        lines.append("失败原因：%s" % _get(data, "error"))
    lines.append("")
    lines.append("继续看：`%s`（不消耗额度）" % client.cmd_line("brainstorm.py", "task %s" % args.task_id))
    print("\n".join(lines) + _source_footer())
    return 0


def cmd_mentors(args) -> int:
    """智囊团成员清单（只读，不消耗额度）。"""
    if getattr(args, "no_cache", False):
        os.environ["OPCRUN_NO_CACHE"] = "1"

    # ★ clamp：--limit 超上限透传会让后端直接 400（与 radar 侧 _clamp_limit 对齐口径）
    limit = args.limit
    if limit is None or limit < 1:
        limit = MENTORS_LIMIT_DEFAULT
    elif limit > MENTORS_LIMIT_MAX:
        sys.stderr.write("提示：mentors 单次最多返回 %d 条，已按 %d 处理\n"
                         % (MENTORS_LIMIT_MAX, MENTORS_LIMIT_MAX))
        limit = MENTORS_LIMIT_MAX

    result = client.get(
        "/skill/board/mentors",
        {"limit": limit},
        ttl=0 if getattr(args, "no_cache", False) else TTL_MENTORS,
        refresh=getattr(args, "refresh", False),
        offline=getattr(args, "offline", False),
    )
    data = result["data"] or {}
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(render_mentors(data))
    return 0


def cmd_quota(args) -> int:
    """
    查询剩余配额。

    ★ 查询失败**不降级成一份看起来正常的配额**：原来 catch 住异常就渲染
      render_usage({})，打印出"身份：已配置 API Key / 额度 - / -"、退出码 0 ——
      与查询成功完全无法区分，Agent 会把"查不到"当成"有额度"。
      现在明确标注失败并返回退出码 5。
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
            print("拿不到真实余额时不要假设还有额度 —— 提交前建议先重试一次。")
            print("本地缓存占用：%s" % _cache_hint())
        return exc.exit_code
    data = result["data"] or {}
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(render_usage(data, result["quota"]))
    return 0


def _cache_hint() -> str:
    stats = client.cache_stats()
    return "%d 条 / %.1f KB（目录：%s）" % (stats["count"], stats["bytes"] / 1024.0, client.CACHE_DIR)


def cmd_auth(args) -> int:
    """
    API Key 的落盘入口：校验 → 保存 → 回显验证结果，一条命令做完。

    用法：
      auth <API_KEY>   校验并保存到本地文件（OPCRUN_HOME/api_key；POSIX 下设为 600 权限）
      auth --status    查看当前 Key 来源与身份（不落盘）
      auth --clear     删除本地保存的 Key
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
                try:
                    result = client.get("/skill/quota", {}, ttl=0, quota_log=False)
                    data = result.get("data") or {}
                    print("- 额度：%s / %s 次/天，重置时间 %s"
                          % (data.get("remaining", "-"), data.get("limit", "-"), data.get("reset_at", "-")))
                except ApiError as exc:
                    print("- 额度查询失败：%s" % exc.message)
                print("- 配置方式：运行 `%s`，或设置环境变量 OPCRUN_API_KEY。"
                  % client.cmd_line("brainstorm.py", "auth <你的API_KEY>"))
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
        print("用法：%s（或 --status / --clear）" % client.cmd_line("brainstorm.py", "auth <API_KEY>"))
        return 1

    # 先用新 Key 验证再落盘：挂到环境变量最前面（resolve_api_key 的第一优先级），用完即还原
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
        # 与 radar 侧 auth 输出对齐：都如实打印套餐层级
        print("- 套餐：%s" % ("免费层" if (data.get("plan") or "") in ("", "free") else data.get("plan")))
        print("- 额度：%s / %s 次/天，重置时间 %s"
              % (data.get("remaining", "-"), data.get("limit", "-"), data.get("reset_at", "-")))
        print("提示：环境变量 OPCRUN_API_KEY 的优先级高于此文件；若此前设置过它，建议移除以免新旧 Key 混用。")
        return 0
    finally:
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
    print("（缓存用于节省配额：导师名录 24 小时、已完成的讨论结果 24 小时）")
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
        prog="brainstorm.py",
        description="OPC.run 超级智囊团：提交问题，拿回一场多角色讨论（0 依赖）",
    )
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("--json", action="store_true", help="输出原始 JSON")
        p.add_argument("--refresh", action="store_true", help="忽略缓存强制联网")
        p.add_argument("--offline", action="store_true", help="只读本地缓存（不消耗配额）")
        p.add_argument("--no-cache", action="store_true", help="本次不读写缓存")

    # ask（POST /skill/board/ask）
    p = sub.add_parser("ask", help="提交一个议题，等讨论结束后输出结果")
    p.add_argument("topic", help="你想让智囊团讨论的问题（10~1000 字，写得越具体越好）")
    p.add_argument("--rounds", type=int, default=ROUNDS_DEFAULT,
                   help="讨论轮数，1~3，默认 2（轮数越多越慢）")
    p.add_argument("--no-wait", action="store_true",
                   help="只提交并打印 task_id，不等结果（稍后用 task 取）")
    p.add_argument("--timeout", type=int, default=IDLE_TIMEOUT_DEFAULT,
                   help="连续多少秒没有新发言就算超时，默认 120（超时后仍可用 task 续查；"
                        "只要讨论还在产出就会继续等）")
    # ★ ask 刻意**不继承 add_common**：提交不读缓存、轮询 ttl=0，
    #   --refresh 对它永远是空操作 —— 注册了却不实现等于静默骗人。
    #   这里只保留真正生效的 --json / --no-cache（后者决定结果是否写入本地缓存）。
    p.add_argument("--json", action="store_true", help="输出原始 JSON（供二次加工）")
    p.add_argument("--no-cache", action="store_true", help="本次讨论的结果不写入本地缓存")
    # --offline 仍注册但在 help 里隐藏：只为在 cmd_ask 里给出明确拒绝 ——
    # 用户以为"离线提交零消耗"、实际照常扣额度，是最不能静默的一种误用
    p.add_argument("--offline", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_ask)

    # task（GET /skill/board/task）
    p = sub.add_parser("task", help="查询一场讨论的结果（续查 / 轮询，不消耗配额）")
    p.add_argument("task_id", help="提交时返回的 task_id")
    add_common(p)
    p.set_defaults(func=cmd_task)

    # mentors（GET /skill/board/mentors）
    p = sub.add_parser("mentors", help="智囊团成员清单（只读，不消耗配额）")
    p.add_argument("--limit", type=int, default=MENTORS_LIMIT_DEFAULT,
                   help="返回条数，最多 %d" % MENTORS_LIMIT_MAX)
    add_common(p)
    p.set_defaults(func=cmd_mentors)

    # quota（GET /skill/quota，注意不在 /board 命名空间下）
    # ★ 不继承 add_common：quota 恒 ttl=0 且每次联网，--offline / --refresh /
    #   --no-cache 对它全是空操作。注册了却做不到，比不注册更容易误导。
    p = sub.add_parser("quota", help="查看剩余配额")
    p.add_argument("--json", action="store_true", help="输出原始 JSON（供二次加工）")
    p.set_defaults(func=cmd_quota)

    # auth（纯本地命令，无 API：校验 + 落盘 API Key）
    p = sub.add_parser("auth", help="配置 API Key：校验并保存（auth <KEY>），或查看/清除（--status / --clear）")
    p.add_argument("key", nargs="?", default="",
                   help="API Key，形如 sk_xxxx（从 opc.run/app/profile/api-keys 获取）")
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
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except client.QuotaExceeded as exc:
        # ★ 引导按身份分流：给匿名用户推注册是转化点，给已注册用户推注册只会让人困惑
        print(exc.message)
        print("")
        if exc.is_anonymous:
            print("🚀 [注册 OPC.run 即可领取免费 API Key](%s)（注册后自动回到智囊团工作台）。"
                  % (exc.register_url or REGISTER_URL))
            print("")
            print("拿到 Key 后按下面三步开启更高额度：")
            print("  1. %s   # 校验并保存到本地（%s）"
                  % (client.cmd_line("brainstorm.py", "auth <你的API_KEY>"), client.key_perm_note()))
            print("  2. %s               # 验证额度已生效" % client.cmd_line("brainstorm.py", "quota"))
            print("  3. 之后正常使用即可，无需每次传 Key")
            print("     （也可以设环境变量 OPCRUN_API_KEY，其优先级高于本地文件）")
            print("")
            print("不着急的话也可以[直接在站内体验完整版](%s)，不受 Skill 额度限制。" % WORKSPACE_URL)
        else:
            print("额度将于 %s 重置。" % (exc.reset_at or "明日 0 点（Asia/Shanghai）"))
            print("💡 已完成的讨论仍可离线查看：给 `task` 子命令加 --offline 参数，不消耗额度。")
            print("   也可以[在站内继续讨论](%s)，不受 Skill 额度限制。" % WORKSPACE_URL)
        return exc.exit_code
    except client.AuthError as exc:
        print(exc.message)
        print("")
        print("🔑 到 [API Keys 页面](%s) 重新生成后，运行 `%s` 保存。"
              % (API_KEYS_URL, client.cmd_line("brainstorm.py", "auth <新Key>")))
        return exc.exit_code
    except client.NotFoundError as exc:
        print(exc.message)
        print("")
        print("💡 task_id 只对**提交它的那个身份**有效，查不到通常是这几种情况：")
        print("   - 匿名提交的那场，换了一台机器（本地 client_id 变了）")
        print("   - 匿名提交的那场，后来配了 API Key —— 身份维度从 client_id 变成账号，")
        print("     服务端不再按 client_id 认领，这场就查不回来了")
        print("   - task_id 打错了（注意：讨论链接里的会话 id 不是 task_id，拿去查会报这个）")
        print("")
        print("   本地缓存可能还在：给 `task` 加 --offline 试试，不消耗额度。")
        print("   配 Key 之后新提交的讨论会跟账号走，随时可查。")
        return exc.exit_code
    except client.PointsRequired as exc:
        # ★ 只有注册用户会碰到（匿名不扣点）。说清三件事：要多少、为什么被拒、怎么办
        print(exc.message)
        print("")
        print("💠 提交一场智囊团讨论需要 **10 点**（与在站内发起一场会议同价）。")
        print("   这次**没有扣点，也没有消耗你的每日额度**。")
        print("")
        print("   - 领点数：[每日签到 / 邀请好友](%s) 领到后重新提交即可" % POINTS_URL)
        print("   - 或者：[去 OPC.run 完整版继续](%s) —— 不受 Skill 额度限制" % WORKSPACE_URL)
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
        sys.stderr.write("\n已中断。讨论仍在服务端继续跑，稍后用 `task <task_id>` 取结果。\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
