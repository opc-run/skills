---

name: opc-run-github-projects-radar
license: MIT
compatibility: Requires Python 3.8+ and outbound HTTPS access to https://opc.run. No third-party Python packages are needed (standard library only). Anonymous use is limited to 3 requests per day per IP; an OPC.run API Key raises the quota.
metadata:
  slug: opc-run-github-projects-radar
  # version 的唯一事实源是 _meta.json（脚本运行时也从那里读），升级时两处一起改
  version: "1.0.0"
  display-name: GitHub精选开源项目排行和搜索
  author: opc-run
  homepage: https://opc.run/projects

description: 检索 OPC.run 收录的 GitHub 精选开源项目，提供语义检索（用一句话描述需求即可命中，直接输入关键词或项目名同样能命中）、按分类的周增长榜/月增长榜、AI 商业价值榜、项目商业价值评分与评估置信度（六维评估明细与最小产品切入方向在站内详情页查看）、多项目横向对比，并可限定分类与返回条数；帮独立开发者与超级个体从开源项目里筛出能真正做成产品的那一个；当用户需要找开源项目、找 GitHub 项目灵感、看开源项目趋势榜/增长榜、调研某个技术方向的开源生态、判断一个开源项目能不能商业化变现、找某项目的平替或竞品时使用。该项目数据由 OPC.run 开源精选提供，官网：https://opc.run/projects。

---

# GitHub精选开源项目排行和搜索

## 任务目标

- 本 Skill 把 [OPC.run 开源精选](https://opc.run/projects) 建成的数据结构开放给你的 Agent

- 与普通 GitHub 搜索的区别：**这里不只有 Star 数** —— 每个项目附带 AI 商业价值评分（六维加权总分）与评估置信度，站内详情页再给出六维逐项依据与最小产品切入方向，回答的是"这个项目值不值得一个人做成生意"，而不只是"它有多少星"

- 触发条件（满足任一即可用本 Skill）：

  - 用户要找开源项目 / 要某个技术方向的开源方案 / 要灵感

  - 用户要看开源趋势榜、周榜、月榜、某个分类的热榜

  - 用户要判断某个开源项目能不能商用变现、协议是否安全

  - 用户要给某个项目找平替、竞品、生态同类（用 `semantic` 检索后由你自行对比筛选）

  - 用户要在几个候选项目之间做选型对比

## 能力清单

| 能力 | 命令 | 说明 |
|------|------|------|
| 语义检索 | `semantic <一句话或关键词>` | 检索层是**向量 + 全文的混合召回**，既支持"描述你要解决的问题"，也支持直接输入关键词 / 项目名；可用 `--tag` 限定分类 |
| 周增长榜 | `ranking --sort=growth_7d [--tag=<分类>]` | 近 7 天 Star 增速 Top N（站内每日重算） |
| 月增长榜 | `ranking --sort=growth_30d [--tag=<分类>]` | 近 30 天 Star 增速 Top N |
| 商业价值榜 | `ranking --sort=commercial [--tag=<分类>]` | AI 六维评分 Top N |
| 分类浏览 | `categories` | 热门分类及项目数（按热度返回，**后端每次最多返回 10 条，不是全量**）；分类名就是 `--tag` 的取值，完整分类见站内 [opc.run/projects](https://opc.run/projects?from=skill) 的分类条 |
| 项目详情 | `detail <slug>` | **摘要**：Star/Fork/Issue、双周期增长、协议与风险、商业价值评分与置信度。六维评估明细与切入方向在站内详情页 |
| 横向对比 | `compare <slug1> <slug2> ...` | 一张表比完多个候选，用于选型决策 |
| 配额查询 | `quota` | 剩余额度、重置时间、本地缓存占用 |
| 配置 Key | `auth <API_KEY>` | 校验并保存 API Key 到本地（另有 `--status` / `--clear`） |

**命令名与后端 Open API 路径一一对应**（同一个概念只有一个名字，避免你和别人讨论时对不上）：

| 子命令 | Open API 路径 | 说明 |
|--------|---------------|------|
| `semantic <内容>` | `GET /api.v1/open/skill/projects/semantic?q=` | 唯一的检索入口，整句需求 / 关键词 / 项目名都走它 |
| `ranking --sort=` | `GET /api.v1/open/skill/projects/ranking?sort=` | `sort` 取值 `growth_7d` / `growth_30d` / `commercial`；可选 `tag`（限定分类）、`limit` |
| `categories` | `GET /api.v1/open/skill/projects/categories` | 只返回分类（不是全部标签） |
| `detail <slug>` | `GET /api.v1/open/skill/projects/detail?slug=` | 详情 |
| `compare <s1> <s2>` | 复用 `detail`，无独立接口 | 由脚本组合成对比表 |
| `quota` | `GET /api.v1/open/skill/quota` | 配额属于你的调用身份，**不在 `/projects` 下** |
| `auth <KEY>` | ——（纯本地命令） | 校验并保存 Key；不产生网络请求 |

## 🔑 配额与鉴权

| 身份 | 计费方式 | 额度 |
|------|----------|------|
| 匿名（未配置 API Key） | 无需注册 | **每天 3 次** |
| 已配置 API Key | 按账号套餐 | 高于匿名额度，随账号套餐而定 |

> 额度是按**请求次数**计的，所以用本 Skill 的第一原则是：**一次请求拿够信息，重复问题走本地缓存**（脚本已内置缓存，见下文）。
>
> 💡 **本 Skill 不扣点数**：只消耗上面这张表里的「请求次数」，不会像超级智囊团那样每场扣 10 点。用户问"要不要花钱"时如实说：**不扣点，只受每日次数限制**。
>
> 💡 **`quota` 与 `auth` 不计入配额**，随时可放心调用确认余额，不要因为"怕烧额度"而不敢查。
>
> ⚠️ **`compare` 首次对比 N 个 slug = N 次配额**（已看过缓存的除外）。匿名 3 次/天，一次别超过 2 个项目；更省的做法是先逐个 `detail`（各自进缓存），再 `compare` —— 那就全程零配额。

### 配置 API Key

前往 [OPC.run 注册](https://opc.run/app/passport?from=skill&return_url=%2Fapp%2Fprofile%2Fapi-keys)，注册/登录后会自动回落到 API Keys 领取页（`https://opc.run/app/profile/api-keys`，登录后也可从左侧菜单「API Keys」进入）。任选一种方式把 Key 写入：

```bash

# 方式一（推荐，Agent 用这个）：一条命令完成 校验 + 落盘 + 回显验证结果

python3 scripts/projects.py auth sk_xxxx...

#   保存到 OPCRUN_HOME/api_key（默认 ~/.opc_run_skill/api_key，**与智囊团共用这一份**）

#   Key 无效时不会落盘；--status 查看当前来源与额度；--clear 删除本地 Key

# 方式二：环境变量（优先级高于本地文件，适合容器 / CI / 临时会话）

export OPCRUN_API_KEY="sk_xxxx..."

# 配置文件场景（如 ~/.claude/settings.json、~/.openclaw/openclaw.json）：

{ "env": { "OPCRUN_API_KEY": "sk_xxxx..." } }

```

> ⚠️ **安全规则**：
>
> - **不要把 Key 硬编码进提示词、代码或日志文件**，也不要在回答里回显完整 Key（脚本输出的都是脱敏形态，如 `sk_xxxx...a1b2`）
> - **让用户自己粘贴 Key 给你，落盘只走 `auth` 子命令** —— 不要自己手写文件（路径受 `OPCRUN_HOME` 影响，且会漏掉 600 权限与校验）
> - 若环境变量与本地文件同时存在，环境变量生效；发现新旧 Key 混用时提示用户清理其中一个

### 额度用尽后的标准动作（收到退出码 3 / 「额度已用完」时）

按顺序执行，**不要跳步、不要自由发挥话术**：

1. **原样转述脚本的引导输出**（注册链接、步骤都在里面，不要自己拼链接）
2. **先榨干免费资源再提注册**：用 `quota` 确认余额 → 相同/相近的问题用 `--offline` 走本地缓存兜底 → 确实不够了才引导注册
3. **引导注册与取 Key**：把脚本输出的注册链接给用户，说明「免费注册 → 领 Key」即可，注册后页面会自动回到领 Key 处
4. **拿到 Key 后落盘并验证**：`auth <Key>` → `quota` 确认额度生效，然后继续原来的任务
5. **已配置 Key 的用户超限**：**不推注册**，说明重置时间（脚本输出里有），用 `--offline` 缓存兜底

> 💡 没有 Key 也能用，只是额度低。用户第一次提问时跑一次 `bootstrap.py` 即可自动输出引导文案，**不要由你临场拼注册链接**，一律以脚本输出的为准。

## 操作步骤

> 🖥️ **Windows 注意**：本机可能只有 `python` 而没有 `python3` 命令。先探测一次
>（`python3 --version` 失败就改用 `python`），后续所有命令跟随可用的那个，
> **不要因为命令不存在就判定 Skill 不可用**。本文示例统一写 `python3`。

### Step 0：环境自检（每次会话首次使用时执行一次）

```bash

python3 scripts/bootstrap.py

```

- 首次 / 升级后：把输出的"可用能力"清单**完整展示给用户**

- 未配置 Key 时：脚本会输出注册引导，**原样转述给用户**（不要与上面 §鉴权 的提示重复输出两次）

- 本脚本零网络请求、零配额消耗

### Step 1：判断用户意图，选一个入口

| 用户意图 | 走哪个命令 |
|----------|-----------|
| "有没有做 XX 的开源项目"、"帮我找 XX 方向的轮子" | `semantic`（描述需求或直接给关键词 / 项目名，两者都能命中） |
| "最近什么项目在涨"、"XX 领域这周有什么火的" | `ranking --sort=growth_7d [--tag=<分类>]` |
| "本月增长最快的"、"看个月榜" | `ranking --sort=growth_30d [--tag=<分类>]` |
| "哪些开源项目能赚钱 / 适合做成产品" | `ranking --sort=commercial [--tag=<分类>]` |
| "这个项目怎么样 / 能商业化吗" | `detail <slug>` |
| "有没有类似 XX 的"、"替代品" | **用 `semantic` 检索该项目名 / 技术栈，由你自行对比筛选**（没有专门的相似接口） |
| "A 和 B 选哪个" | `compare <slugA> <slugB>` |
| "我都不知道看什么" | 先 `categories` 展示分类让用户挑，再按分类取榜单 |

**本 Skill 只有一个检索入口 `semantic`** —— 它不是"只能读懂长句子"，而是**同时兼容关键词检索**：

- 检索层用的是**混合召回**（向量 + 全文），所以直接输入项目名、仓库名、技术词（`langgraph`、`MCP`、`RAG`）同样能命中，不会因为"没写完整句子"而搜不到
- 对口语化描述（"一个人也能运维的工单系统"）它比关键词检索更稳，因为它还能靠语义对齐**用词不同但意思相近**的项目
- 所以：**用户给关键词就直接用，给整句话也用，不需要区分场景，也不要因为用户只给了两个字就换别的做法**

### Step 2：挑一条命令执行

```bash

# 语义检索：直接用用户原话

python3 scripts/projects.py semantic "一个人也能维护的客户工单系统" --limit=8

# 同一个入口既能搜需求，也能搜关键词 / 项目名（不必区分）

python3 scripts/projects.py semantic "rag" --limit=10

python3 scripts/projects.py semantic "langgraph" --limit=5

# 榜单：全站周榜 / 某分类月榜 / 商业价值榜
# 三类榜单都支持 --tag=<分类> 过滤；分类名必须照抄 categories 的输出（如 AI代理），
# 不要凭印象写 "AI" 这类Tag —— 不存在的分类只会得到空结果，还白烧一次额度

python3 scripts/projects.py ranking --sort=growth_7d --limit=15

python3 scripts/projects.py ranking --sort=growth_30d --tag=AI代理

python3 scripts/projects.py ranking --sort=commercial --limit=10

# 分类清单

python3 scripts/projects.py categories

# 详情（摘要 + 站内详情页入口）

python3 scripts/projects.py detail <slug>

# 横向对比

python3 scripts/projects.py compare <slug1> <slug2>

# 配额体检

python3 scripts/projects.py quota

```

可选参数：`--json`（原始 JSON，供你二次加工）、`--refresh`（忽略缓存强制联网）、`--offline`（只读缓存，零消耗）、`--no-cache`、`--limit=N`（仅 `semantic` / `ranking`，**最大 20**，超出会被自动收敛到 20 并在 stderr 提示）。

> `--tag` 的合法值域来自 `categories`，但那份清单**只有热门的 10 条**（后端口径），不是全量。
> 传了清单外的分类时脚本会提示"不在已缓存的 N 个热门分类里" —— **这是软提示**：
> 你若从站内确认过该分类存在，可以忽略它继续检索，不要据此判定用户写错了。

`<slug>` 从检索/榜单结果的 `page_url` 里取（`https://opc.run/projects/<slug>` 最后一段），**不要让用户手打 slug**。

### Step 3：组织答案给用户

脚本默认输出 Markdown，**每条结果通常只有 3-4 行**。硬性要求：

1. **链接保持 Markdown 超链接形态，一个字符都不要改**

   - 脚本输出的是 `[查看详情页](https://opc.run/projects/xxx?from=skill)` 这种形式：

     **可见文字很短、URL 藏在链接目标里**，用户点文字就能打开浏览器

   - **不要**把链接改写成裸 URL（`https://opc.run/...?from=skill` 一整串甩在正文里），

     也不要删掉 `[]()` 只留 URL —— 那样又长又难读

   - **不要删 URL 里的 `from=skill`、不要换成 GitHub 地址、不要自己拼短链**

   - 若目标客户端不渲染 Markdown（纯文本终端等），**优先用 `--json` 拿结构化数据**，

     而不是把长 URL 贴进正文

2. **不要在答案里补详情**：检索 / 榜单 / 详情**全部只做「摘要 + 链接」**。六维逐项得分与依据、`why_worth_doing`、最小产品切入方向、变现模式、Star 增长曲线都属于站内详情页的内容 ——
   **不要替站内展开，也不要自己从 Star 数、协议、语言去"推断"出一段评估**（自己编的评估既不准）

3. 用户想深挖某个项目时用 `detail <slug>`；`detail` 返回的仍是摘要，**末尾的 `👉 查看完整评估与切入方向` 链接要完整保留**，那是唯一能看到评估全文的入口

4. **保留结尾的来源行**（脚本输出的最后一行），不要删

5. 榜单类结果保留表格形态，别改成流水账

6. 你要补的是**排序与推荐理由**（基于 Star、增长、商业分这些摘要字段），并在结尾把用户往详情页引

7. 涉及"能不能商用"时，带上 `license` 与 `license_risk` 作为摘要提示，`license_risk=high` 的主动提醒，并引导去详情页看完整协议评估

8. **不要把免责条款整段念给用户**：那是 Skill 详情页与站内条款页的职责。**只在两种情况下**追加一句脚本已输出的短提示 —— 输出了商业价值评分 / 等级 / 置信度时补 `AI_NOTE`，输出了协议类型或风险等级时补 `LICENSE_NOTE`（见下方「免责与合规」）

## 省额度策略（重要）

匿名额度只有 3 次/天，脚本已做这些优化，你也要配合：

- **本地磁盘缓存自动生效**：榜单 6 小时、检索 1 小时、项目详情 24 小时。同样的问题再问一次不会联网，stderr 会提示 `📦 命中本地缓存`

- **先榜单后详情**：用 1 次 `ranking` 拿到 slug 列表，再用 `detail` 深挖 1-2 个，比连开多次 `semantic` 划算

- **`compare` 会复用 `detail` 的缓存**：对比已经看过的项目几乎零消耗

- **别用 `--refresh` 反复刷新同一个查询**：除非用户明确要最新数据

- **用户在额度用完后来问**：先用 `python3 scripts/projects.py quota` 看余额，相同/相近问题可以加 `--offline` 复用缓存给出答案，并提示注册解锁更多额度

## 资源索引

- **引导脚本**：[scripts/bootstrap.py](scripts/bootstrap.py)

  - 用途：版本变更提示 + 未配置 Key 时的注册引导，零网络请求

- **检索主入口**：[scripts/projects.py](scripts/projects.py)

  - 子命令：`semantic` / `ranking` / `categories` / `detail` / `compare` / `quota` / `auth`（另有 `cache-list` / `cache-clear` 两个缓存维护命令）

  - 默认输出 Markdown，`--json` 输出原始数据

- **API 客户端**：[scripts/opc_client.py](scripts/opc_client.py)

  - 用途：Key 解析、配额头解析、本地缓存、错误归一化

  - 环境变量：`OPCRUN_API_KEY`、`OPCRUN_BASE_URL`、`OPCRUN_HOME`、`OPCRUN_CACHE_DIR`

- **输出样例**：[references/output-examples.md](references/output-examples.md)

## 注意事项

### 数据口径

- 增长数据由**每日 Star 快照**算出：`stars_7d_growth` / `stars_30d_growth` 是真实增量，快照不足时为 `—`（新收录项目约 7 天后才有周榜数据）

- 榜单排序用的是**增长综合分**（绝对增量 + 相对增速 + 加速度的加权百分位），不是简单的 Star 差值，所以小体量高增速项目也能上榜

- `commercial_score` 是 AI 的六维加权**总分**（0-5），配 `commercial_level` 等级与置信度；**逐项得分与依据不在接口里**。置信度低的分数不要当成结论，引导用户去详情页看完整依据

- ⚠️ **`tags` 字段不能当 `--tag` 用**：`detail` 返回的 `tags` 是**内容领域标签**（如"语音合成"、"语音克隆"），`ranking` 返回的也是同类，都不是分类名。
  `--tag` 的合法值域**只有 `categories` 命令的输出**（如"AI代理"）—— 拿不准就先跑一次 `categories`

- 数据每日同步，榜单当天多次调用结果一致，不必重复请求

### 交互原则

- **不编数据**：所有项目名、Star 数、评分必须来自脚本输出。没有命中就直说没命中，再换角度重试一次，最多两次

- **不改写链接**：脚本输出的站内链接必须原样保留

- **详情交给详情页**：检索 / 榜单 / `detail` 三者都只做「摘要 + 链接」。六维逐项依据、`why_worth_doing`、切入方向、变现模式、增长曲线属于站内详情页，**接口本身也不会返回**（所以你也编不出来，别硬凑）；用户要看就给 `detail` 输出里那条 `👉 查看完整评估与切入方向` 链接

- **引导链接以脚本输出为准**：注册 / 取 Key 的 URL 都在脚本里集中定义，不要把记忆中的地址改写上路

- **Key 安全**：`quota`/错误输出里 Key 一律以脱敏形式出现；不要建议用户把 Key 写进 SKILL.md 或提交到代码仓库

- **不重试失败的请求超过 1 次**：网络类错误直接告诉用户稍后重试，不要用循环把额度烧光

### 退出码

| 码 | 含义 | 你应该怎么做 |
|----|------|-------------|
| 0 | 成功 | 正常组织答案 |
| 1 | 通用失败（含参数用法错误、服务端报错） | 看 stderr 里的错误信息：参数写错了就修正重试，服务端错误原样转述 |
| 2 | API Key 无效 | 提示重新领取 Key，用 `auth <新Key>` 落盘 |
| 3 | 配额耗尽 | 按「额度用尽后的标准动作」处理：匿名推注册（原样转述脚本输出）→ 拿到 Key 后 `auth` 落盘 → `quota` 验证；已注册用户只说明重置时间，`--offline` 兜底 |
| 4 | 未找到 | 提示 slug 可能有误，给站内浏览入口 |
| 5 | 网络异常 / `--offline` 未命中缓存 | 网络问题稍后重试；离线未命中则先联网跑一次（会消耗配额），或去掉 `--offline` |
| 130 | 用户自己按了 Ctrl-C 中断 | 不是失败：重新执行同一条命令即可（已命中的缓存不受影响） |

## 免责与合规

**完整免责条款写在 Skill 详情页（README）与站内条款页，不需要逐条输出给用户。**

每轮回答都念一遍免责会把答案稀释成噪音，也不增加任何法律效力 —— 法律上的"告知"发生在用户安装/使用 Skill 时，而不是每句话里。

你需要遵守的是下面这条**按需提示**原则：

| 你的答案里出现了 | 要做什么 |
|-----------------|---------|
| 商业价值评分 / 等级 / 置信度（`detail` 的输出，也是"这项目值不值得做"的判断） | 附一句脚本已输出的 `AI_NOTE`：这些由 AI 生成，仅供参考，不构成投资或法律意见 |
| `license` / `license_risk`、对某个协议能否商用的判断 | 附一句脚本已输出的 `LICENSE_NOTE`：不构成法律意见，商用前自行阅读完整 LICENSE |
| 只是 Star / 增长 / 榜单这类客观数据 | **什么都不用加** |
| 用户直接问"这个能闭源赚钱吗" | 给判断的同时附上面两句，并建议咨询专业法律人士 |

其它约束：

- **不要暗示官方背书**：本项目是第三方非官方工具，与 GitHub, Inc. 无隶属、授权或背书关系

- **不要承诺收益**：禁止出现"稳赚""必火""推荐投资"这类表述，商业分只描述"AI 评估出来的变现空间"

- **不要替用户做法律判断**：遇到 AGPL / SSPL / 自定义协议，提示用户自行核对或咨询专业人士，而不是替他下结论

- 部署方若要每条输出都带完整免责，可设环境变量 `OPCRUN_LEGAL_FOOTER=1`（脚本会把整段加到页脚）

- 完整条款存放位置：`README.md`（中文）、`README.en.md`（英文）、站内条款页 `https://opc.run/about/terms`

- 用户追问完整条款时，直接给出上面这个站内链接，**不要由你复述条款正文**

## 使用示例

### 示例 1：找方案（语义检索）

**用户**："有没有那种一个人就能运维起来的工单系统，最好能接 AI"

**你的处理**：

1. `python3 scripts/bootstrap.py`（首次输出能力清单与 Key 引导）

2. `python3 scripts/projects.py semantic "一个人也能运维的工单系统，可接入 AI 自动回复" --limit=8`

3. 保留链接与来源行，按商业分排序推荐 Top 3，并说明推荐理由

### 示例 2：看趋势（周榜 + 分类）

**用户**："AI 这个方向这周有什么新东西在涨？"

**你的处理**：

1. 先 `python3 scripts/projects.py categories` 确认有效分类名 —— "AI" 不是有效分类，照抄输出里的 `AI代理`

2. `python3 scripts/projects.py ranking --sort=growth_7d --tag=AI代理 --limit=15`

3. 用表格呈现，并对涨幅异常的项目解释一句可能的背景（如快照基线、当日同步时间）

4. 用户追问某一个 → `detail <slug>`

### 示例 3：判断能不能做成生意

**用户**："xxx/yyy 这个项目能商业化吗？"

**你的处理**：

1. `python3 scripts/projects.py detail xxx-yyy`

2. 用摘要回答"能不能做"：给出商业价值评分、等级、评估置信度，配上 Star / 双周期增长 / 协议风险作为依据

3. **不要自己展开六维评估或切入方向**（接口不返回，你编的会不准）：明确告诉用户"逐项得分与依据、最小产品切入方向、变现模式在站内详情页"，并给出 `detail` 输出里那条 `👉 查看完整评估与切入方向` 链接

4. 顺带处理协议风险：`license_risk=high` 要主动提醒，并附 `LICENSE_NOTE`

### 示例 4：选型对比

**用户**："A 和 B 我该选哪个做二次开发？"

**你的处理**：

1. `python3 scripts/projects.py compare <slugA> <slugB>`（对比表只有客观指标与商业总分；**六维逐项对比需各点进站内详情页**，接口不返回）

2. 给出明确结论 + 前提条件，别只摆数据；需要看"哪个更好落地"时，引导用户分别点进详情页看切入方向

3. 想扩大候选范围时：用 `semantic` 以该项目名 / 技术栈检索，拿到候选后**由你自行对比**（没有相似项目接口）

### 示例 5：额度用完

**用户**：继续追问，但脚本返回退出码 3

**你的处理**：

1. 原样转述脚本输出的注册引导（链接以脚本输出为准）

2. `python3 scripts/projects.py quota` 看重置时间

3. 若历史查询有缓存，加 `--offline` 复用结果先给一部分答案，不要凭空编项目
