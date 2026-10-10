# 输出样例

以下为 `scripts/projects.py` 默认（Markdown）输出的样例。Agent 应在此基础上加工，硬性要求：

1. **链接一律保持 Markdown 超链接形态**：`[可见文字](完整URL)`。可见文字很短，URL（含 `from=skill`）藏在链接目标里，
   对话界面点文字即可打开浏览器；**不要把链接改写成一整串裸 URL 贴进正文**。
2. **`from=skill` 不能删**：删掉就等于让站点无法识别这部分流量来自 Skill。
3. **只做摘要**：检索 / 榜单 / `detail` **都只给摘要 + 链接**。六维逐项依据、切入点、变现模式、增长曲线在站内详情页，接口不返回这些字段，所以也不要试图从 Star / 协议去"推断"出一段评估补上。

## 1. 语义检索

> 样例中的项目都已在库内核实过（详情页 200），**不要用未核实存在的项目编样例** —— Agent 照抄一个 404 链接，等于把用户送进死胡同。

```
$ python3 scripts/projects.py semantic "有没有适合一个人做的开源 AI Agent 框架" --limit=3
```

```markdown
### 语义检索：有没有适合一个人做的开源 AI Agent 框架（3 个）

**1. [langchain-ai/langgraph](https://opc.run/projects/langchain-ai-langgraph?from=skill)**
  ⭐ 21.0k ｜ 🔧 Python ｜ 📈 周 +420 / 月 +1,900 ｜ 💰 商业分 4.35 ｜ 📜 MIT
  Build resilient language agents as graphs.
  👉 [查看详情页：六维评估 · 增长曲线 · 变现建议](https://opc.run/projects/langchain-ai-langgraph?from=skill)

**2. [browser-use/browser-use](https://opc.run/projects/browser-use-browser-use?from=skill)**
  ⭐ 48.2k ｜ 🔧 Python ｜ 📈 周 +1,204 / 月 +5,330 ｜ 💰 商业分 4.02 ｜ 📜 MIT
  让 AI Agent 直接操作浏览器的自动化框架。
  👉 [查看详情页：六维评估 · 增长曲线 · 变现建议](https://opc.run/projects/browser-use-browser-use?from=skill)

**3. [mem0ai/mem0](https://opc.run/projects/mem0ai-mem0?from=skill)**
  ⭐ 24.6k ｜ 🔧 Python ｜ 📈 周 +512 / 月 +2,180 ｜ 💰 商业分 4.10 ｜ 📜 Apache-2.0
  给 Agent 加记忆层的开源方案。
  👉 [查看详情页：六维评估 · 增长曲线 · 变现建议](https://opc.run/projects/mem0ai-mem0?from=skill)

🔗 完整榜单与实时增长数据：[opc.run/projects](https://opc.run/projects?from=skill)

---

数据来源：OPC.run 开源精选 · [opc.run/projects](https://opc.run/projects?from=skill)
```

## 2. 周增长榜

```
$ python3 scripts/projects.py ranking --sort=growth_7d --tag=AI代理 --limit=3
```

> 分类名要用 `categories` 返回的**原名**（如 `AI代理`），不要凭印象写"AI"——不存在的分类只会得到空结果。

```markdown
### 周增长榜（近 7 天 Star 增速） · AI代理 Top 3（快照日期：2026-10-02）

| # | 项目 | Star | 周增 | 月增 | 商业分 | 语言 | 协议 |
|---|---|---|---|---|---|---|---|
| 1 | [langchain-ai/langgraph](https://opc.run/projects/langchain-ai-langgraph?from=skill) | 21.0k | +420 | +1,900 | 4.35 | Python | MIT |
| 2 | [browser-use/browser-use](https://opc.run/projects/browser-use-browser-use?from=skill) | 48.2k | +1,204 | +5,330 | 4.02 | Python | MIT |
| 3 | [mem0ai/mem0](https://opc.run/projects/mem0ai-mem0?from=skill) | 24.6k | +512 | +2,180 | 4.10 | Python | Apache-2.0 |

👉 点击表格中的项目名即进入站内详情页。
🔗 榜单持续更新，站内可按分类查看：[opc.run/projects](https://opc.run/projects?from=skill)

---

数据来源：OPC.run 开源精选 · [opc.run/projects](https://opc.run/projects?from=skill)
```

## 3. 项目详情（同样是摘要）

```
$ python3 scripts/projects.py detail langchain-ai-langgraph
```

```markdown
### [langchain-ai/langgraph](https://opc.run/projects/langchain-ai-langgraph?from=skill)

- 仓库：<https://github.com/langchain-ai/langgraph>
- Star：21.0k ｜ Fork：3.2k ｜ Open Issues：180
- 增长：近 7 天 +420 ｜ 近 30 天 +1,900
- 语言：Python ｜ 协议：MIT（风险：low）
- 商业价值评分：**4.35 / 5**（强烈推荐） ｜ 评估置信度：86%
- 标签：AI、Agent、Python

**简介**：Build resilient language agents as graphs.

🔒 **以下内容在站内详情页，本 Skill 不返回**：
   痛点强度、目标客户清晰度、二次开发可行性、个人可独立完成、变现空间、协议友好度的逐项得分与依据 · 最小产品切入方向 · 变现模式 · Star 增长曲线

注：以上评分与建议由 AI 生成，仅供参考，不构成投资或法律意见。
注：协议与风险等级为自动识别，不构成法律意见；商用前请自行阅读完整 LICENSE。

👉 [查看完整评估与切入方向](https://opc.run/projects/langchain-ai-langgraph?from=skill)

---

数据来源：OPC.run 开源精选 · [opc.run/projects](https://opc.run/projects?from=skill)
```

> 注意最后那条 `👉` 链接：它是用户看到评估全文的**唯一入口**，也是 `detail` 这条命令存在的意义，**不要删、不要改成 GitHub 地址**。

## 4. 配额输出

```markdown
### 配额使用情况

- 身份：匿名（未配置 API Key）
- 额度：2 / 3 次（窗口：day）
- 重置时间：2026-10-03 00:00:00
- 套餐：匿名（接口返回 `anonymous`，输出时会翻成可读文案）
- 本地缓存：6 条 / 41.2 KB（命中缓存不消耗配额）

> 💡 `quota` 查询本身**不计入配额**，随时可以放心用它确认余额再决定要不要联网检索。

🚀 匿名额度有限。[注册 OPC.run 免费领取 API Key](https://opc.run/app/passport?from=skill&return_url=%2Fapp%2Fprofile%2Fapi-keys)，额度大幅提升。
   已有账号？[在这里取 Key](https://opc.run/app/profile/api-keys?from=skill)。

---

数据来源：OPC.run 开源精选 · [opc.run/projects](https://opc.run/projects?from=skill)
```

## 5. stderr 侧的日志（不进入答案正文）

```
🔢 配额[匿名] 2/3，重置时间 2026-10-03 00:00:00
💡 匿名额度仅剩 1 次/天。[注册账号领取 API Key](https://opc.run/app/passport?from=skill&return_url=%2Fapp%2Fprofile%2Fapi-keys) 可大幅提升额度（免费）。
📦 命中本地缓存（2.3 小时前），本次不消耗配额
```

## 6. 来源参数

所有指向站内的链接统一带 `?from=skill`（已带 query 的用 `&` 拼接），由脚本自动生成，**不要删、也不要改值**。
站点据此统计来自 Skill 的流量；来源参数不含任何用户信息。
