#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc-run-super-brainstorm / scripts / bootstrap.py

每次使用本 Skill 前执行一次，负责两件事：
  1. 版本变更提示：首次安装 / 升级后展示新增能力，版本一致时静默无输出
  2. 额度体检：检查是否已配置 OPC.run API Key，未配置则输出注册引导

本脚本**不发起任何网络请求**，不消耗配额。

用法：python3 scripts/bootstrap.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opc_client as client  # noqa: E402

# 版本号唯一来源是 _meta.json（opc_client.VERSION 也从那里读），别在这里再硬编码一份
CURRENT_VERSION = client.VERSION
# ★ 落在共享状态目录里（跟随 OPCRUN_HOME），但文件名带 Skill slug：
#   两个 Skill 共用同一个 OPCRUN_HOME 时，各自的「首次可用能力清单」不会被对方的
#   版本标记吃掉（共用一份 version 时，先跑的那个会让后跑的那个静默无输出）。
VERSION_FILE = client.HOME_DIR / ("version-%s" % client.SKILL_SLUG)

# 链接**只从 opc_client 取**，不要在本文件另写一份：
# 两处定义必然漂移（改了来源参数或落地页，另一处还是旧的）
REGISTER_URL = client.REGISTER_URL
API_KEYS_URL = client.API_KEYS_URL
INTRO_URL = client.INTRO_URL
WORKSPACE_URL = client.WORKSPACE_URL

CHANGELOG = {
    "1.0.0": {
        "title": "超级智囊团 v1.0.0",
        "highlights": [
            "🧠  一句话开一场圆桌\n"
            "     把问题丢进来，系统自动挑 3~5 位最对口的导师，按轮次交叉发言、互相点名接话\n"
            "     用法：%s" % client.cmd_line("brainstorm.py", 'ask "你的问题"'),

            "📋  不是同一个 AI 换头像\n"
            "     每位导师按自己的人设与思维模型发言，后面的人听着前面的人接话、反驳、点名下一位\n"
            "     最多 3 轮，说完就停 —— 想要一个明确的结论，请去站内完整版",

            "💾  讨论取回来很方便\n"
            "     每场讨论都有一个 task_id，随时能再取回来看；\n"
            "     配上 API Key，额度更高，讨论还能在站内接着追问导师",

            "👥  随时看智囊团都有谁\n"
            "     %s（只读，不消耗额度）" % client.cmd_line("brainstorm.py", "mentors"),

            "🪶  零依赖 + 本地缓存\n"
            "     纯 Python 标准库，无需 pip install\n"
            "     已完成的讨论本地缓存，重复查看不再消耗额度",
        ],
    }
}


def read_stored_version() -> str:
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def save_version(version: str) -> None:
    try:
        VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        VERSION_FILE.write_text(version, encoding="utf-8")
    except OSError:
        pass


def show_version_notes() -> None:
    stored = read_stored_version()
    if stored == CURRENT_VERSION:
        return
    entry = CHANGELOG.get(CURRENT_VERSION, {})
    highlights = entry.get("highlights", [])
    # ★ CHANGELOG 里没有当前版本条目时（升级时漏改 / 自定义版本号），
    #   不要打印一个下面空空如也的"新增能力："标题 —— 那看起来像脚本坏了。
    if not stored:
        print("👋 欢迎使用 %s！" % entry.get("title", "超级智囊团"))
    else:
        print("🔄 已从 v%s 升级至 v%s" % (stored, CURRENT_VERSION))
    if highlights:
        print("")
        print("本次可用能力：" if not stored else "新增能力：")
        print("")
        for item in highlights:
            print("  %s" % item)
            print("")
    save_version(CURRENT_VERSION)


def check_api_key() -> None:
    """未配置 API Key 时输出一次注册引导（不阻塞，匿名仍可用）。"""
    # 判定逻辑与 opc_client.resolve_api_key 保持同一事实源：
    # KEY_FILE 支持 OPCRUN_KEY_FILE 自定义路径，硬编码 HOME/api_key 会误报
    if client.resolve_api_key():
        return
    print("─" * 52)
    print("当前为匿名模式：每天 3 场讨论。")
    print("[注册 OPC.run 并领取免费 API Key](%s)，额度更高，讨论还能在站内接着追问导师。" % REGISTER_URL)
    print("已有账号？登录后从左侧菜单「API Keys」进入即可领取：[打开 API Keys 页面](%s)" % API_KEYS_URL)
    print("拿到 Key 后一条命令完成校验与保存（不要把 Key 写进提示词或日志）：")
    print("    %s" % client.cmd_line("brainstorm.py", "auth <你的 Key>"))
    print("─" * 52)
    print("")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    show_version_notes()
    check_api_key()
    print("超级智囊团：[opc.run/session](%s) ｜ 直接开一场：[opc.run/app/session/list](%s)"
          % (INTRO_URL, WORKSPACE_URL))
    print("免责与条款见本 Skill 的 SKILL.md / README，[公开版本](%s)" % client.TERMS_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
