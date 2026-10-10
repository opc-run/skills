# OPC.run Skills

[OPC.run](https://opc.run) 的官方 Agent Skills。面向独立开发者与超级个体的实用工具集 —— 每个 Skill 都是**零第三方依赖**（纯 Python 标准库），装上就能用。

> 本仓库遵循 [Agent Skills 开放规范](https://agentskills.io/specification)，可被 Claude Code、Cursor、GitHub Copilot、Codex CLI、Windsurf 等 20+ 种 Agent 直接读取。

---

## Skills

### [`opc-run-super-brainstorm`](opc-run-super-brainstorm/) — 超级智囊团

把一个问题交给 AI 智囊团，自动挑 3~5 位最对口的导师开一场多角色圆桌讨论。

- **观点真的会碰撞**：每位导师带着各自的人设、思维模型与决策准则，后面的人听着前面的人接话、反驳、点名下一位 —— 不是"一个 AI 换三种语气"
- **边讨论边看，不用干等**：某位导师说完你就能读到，不要坐着等它跑完（导师越多越慢，一场通常要几分钟）
- **分歧本身就是价值**：几位导师各抒己见就停在这儿 —— 想把分歧收敛成一份可执行的结论、想继续追问、想中途插话，去站内完整版

```bash
python3 opc-run-super-brainstorm/scripts/brainstorm.py ask "我是一个人做跨境电商的卖家，月流水 3 万，该不该现在招第一个全职？"
```

匿名**每天 3 场**（不扣点；配 Key 后额度更高，但**每场扣 10 点**）。[查看详情 →](opc-run-super-brainstorm/)

---

### [`opc-run-github-projects-radar`](opc-run-github-projects-radar/) — GitHub 精选开源项目排行和搜索

一句话找开源项目，但**不只是 Star 数**。

- **一个检索入口就够**：描述需求能命中，直接给关键词 / 项目名同样能命中（向量 + 全文混合召回）
- **增长榜单**：周榜 / 月榜按「增长综合分」排序，小体量高增速项目也能上榜
- **能赚钱吗**：每个项目一个 AI 商业价值总分 + 等级 + 置信度；六维评估依据与最小产品切入方向在站内详情页

```bash
python3 opc-run-github-projects-radar/scripts/projects.py semantic "一个人也能维护的客户工单系统"
```

匿名**每天 3 次请求**。[查看详情 →](opc-run-github-projects-radar/)

---

## 安装

### 方式一：npx skills（推荐）

```bash
# 装单个
npx skills add opc-run/skills/opc-run-super-brainstorm

# 全局安装（所有项目可用）
npx skills add opc-run/skills/opc-run-super-brainstorm --global
```

### 方式二：Claude Code 插件市场

```
/plugin marketplace add opc-run/skills
/plugin install opc-run-super-brainstorm@opc-run-skills
```

### 方式三：手动

```bash
git clone https://github.com/opc-run/skills.git   # 克隆出来的目录名就是 skills
cp -r skills/opc-run-super-brainstorm ~/.claude/skills/
```

**路径口径**：下面所有示例都从**仓库根目录**（克隆出来的 `skills/`，两个 Skill 目录与 README 平级）执行；把某个 Skill 单独装进 `~/.claude/skills/` 后，请在**该 Skill 目录内**执行，命令里的 `opc-run-xxx/scripts/` 换成 `scripts/`。

Windows 上若没有 `python3` 命令，把下面所有示例里的 `python3` 换成 `python`。

---

## 共同约定

| | |
|---|---|
| **依赖** | 纯 Python 标准库，无需 `pip install` |
| **配置** | 环境变量 `OPCRUN_API_KEY`（可选，配了额度更高）；也可用任一 Skill 的 `auth` 子命令落盘 |
| **本地状态** | `~/.opc_run_skill/`：**API Key 两个 Skill 共用**（在智囊团里配的 Key 开源榜直接可用）；**缓存各自分开**（`cache/<skill>/`，清缓存、缓存条数都只算自己那一份）；想整体独立就设 `OPCRUN_HOME` |
| **网络** | 只向 `https://opc.run` 一个域名发请求，无第三方 SDK、无遥测上报第三方 |

### 提升额度（可选）

两个 Skill 匿名都能用，**每天 3 次**（智囊团是 3 场讨论，开源排行是 3 次检索）。免费注册即可提升到按账号套餐的额度（free 30/天），配置方式：

> ⚠️ **智囊团配了 API Key 之后，每场讨论扣 10 点**（与站内发起一场会议同价；讨论失败自动退点）。
> 匿名**不扣点**；开源排行无论是否配 Key 都**不扣点**，只受每日次数限制。

```bash
python3 opc-run-super-brainstorm/scripts/brainstorm.py auth sk_xxxx...   # 校验并保存到本地（POSIX 下设为 600 权限）
# 或
export OPCRUN_API_KEY="sk_xxxx..."
```

- 注册：[opc.run/app/passport](https://opc.run/app/passport?from=skill)
- 领取 Key：[opc.run/app/profile/api-keys](https://opc.run/app/profile/api-keys?from=skill)

---

## 隐私

两个 Skill 都会把你提交的**问题原文**发送到 `https://opc.run` 由服务器处理，**不会发送给任何其他第三方**。

除了请求本身，还会上报匿名遥测（Skill 名称与版本、本地随机安装标识、IP）用于统计调用量与内容缺口。API Key 只用于 `Authorization` 请求头，不会写入日志或输出文件。

请勿提交涉密信息、个人隐私或你无权披露的商业秘密。

---

## 免责声明

1. **AI 生成内容**：Skill 输出的导师发言，以及站内展示的推演过程与结论，全部由 AI 生成，**不构成投资建议、法律意见、医疗建议或任何商业决策的保证**。导师是人格化设定（基于公开人物的方法论与思维模型构建），**不代表本人言论**，也不代表 OPC.run 的观点。
2. **不承诺结果**：Skill 提供的是观点参考，不是结论。
3. **数据留存**：提交的内容会保存在 OPC.run。OPC.run 保留随时调整额度、变更或终止服务的权利。
4. **自行承担**：据此产生的决策后果由用户自行承担。

完整条款：<https://opc.run/about/terms>

---

## 许可

[MIT](LICENSE)
