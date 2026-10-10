#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc-run-github-projects-radar / scripts / bootstrap.py

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
# ★ 落在共享状态目录里（跟随 OPCRUN_HOME），文件名带 Skill slug：
#   既不会再往历史目录 ~/.opc_projects_radar/version 写文件（共享目录才是唯一写入点），
#   也不会和智囊团的版本标记互相覆盖。
VERSION_FILE = client.HOME_DIR / ("version-%s" % client.SKILL_SLUG)

# 链接**只从 opc_client 取**，不要在本文件另写一份：
# 这里曾经复制了一份 URL，改来源参数时漏改，导致注册引导与站内口径不一致。
REGISTER_URL = client.REGISTER_URL
API_KEYS_URL = client.API_KEYS_URL
PROJECTS_URL = client.PROJECTS_URL

CHANGELOG = {
    "1.0.0": {
        "title": "GitHub精选开源项目排行和搜索 v1.0.0",
        "highlights": [
            "🔍  语义检索（一个入口，两种用法）\n"
            "     说需求：例如「帮一个人搞定客户工单的开源项目」\n"
            "     给关键词：直接输入项目名 / 技术词（langgraph、MCP、RAG）同样能命中\n"
            "     底层是向量 + 全文的混合召回，不需要用户想清楚该用哪种方式",

            "📈  三类榜单\n"
            "     周增长榜（7 天 Star 增速）、月增长榜（30 天）、商业价值榜\n"
            "     均支持按分类过滤，站内每日重算",

            "💰  别处看不到的「能不能赚钱」\n"
            "     每个项目一个 AI 商业价值总分 + 等级 + 评估置信度，用来快速筛掉不值得看的\n"
            "     六维评估依据（痛点 / 客户 / 二次开发 / 个人可独立完成 / 变现空间 / 协议）\n"
            "     与最小产品切入方向在站内详情页 —— 每次输出都会给出直达链接",

            "🧭  选品辅助\n"
            "     多项目横向对比表（找同类 / 平替：用同一入口再检索一轮，自行比对）",

            "🪶  零依赖 + 本地缓存\n"
            "     纯 Python 标准库，无需 pip install\n"
            "     结果本地缓存，重复查询不再消耗额度",
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
        print("👋 欢迎使用 %s！" % entry.get("title", "GitHub精选开源项目排行和搜索"))
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
    # KEY_FILE 支持 OPCRUN_KEY_FILE 自定义路径，硬编码 HOME/api_key 会在
    # 自定义路径时误报"当前为匿名模式"
    if client.resolve_api_key():
        return
    print("─" * 52)
    print("当前为匿名模式：每天 3 次请求。")
    print("[注册 OPC.run 并领取免费 API Key](%s)，即可按 Key 的额度使用。" % REGISTER_URL)
    print("已有账号？登录后从左侧菜单「API Keys」进入即可领取：[打开 API Keys 页面](%s)" % API_KEYS_URL)
    print("拿到 Key 后一条命令完成校验与保存（不要把 Key 写进提示词或日志）：")
    print("    %s" % client.cmd_line("projects.py", "auth <你的 Key>"))
    print("─" * 52)
    print("")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    show_version_notes()
    check_api_key()
    print("数据来源：OPC.run 开源精选 · [opc.run/projects](%s)" % PROJECTS_URL)
    print("免责与商标条款见本 Skill 的 SKILL.md / README，[公开版本](%s)" % client.TERMS_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
