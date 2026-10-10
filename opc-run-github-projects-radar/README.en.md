# GitHub Projects Radar / opc-run-github-projects-radar

---

## Overview

Find open-source projects by describing what you need — and get more than a star count.

This skill connects to [OPC.run Open Source Picks](https://opc.run/projects), which tracks daily GitHub snapshots and runs a six-dimension AI business assessment on every indexed repository. It answers the questions a star count cannot: can one person actually ship this, can it become a business, and is the license safe for commercial use.

**Core value**

- **One search entry point**: hybrid retrieval (vector + full text) — describe the problem in a sentence, or simply give a keyword / repo name; both work

- **Growth rankings**: weekly / monthly lists sorted by a composite growth score (absolute delta + relative velocity + acceleration, percentile-weighted), so small fast-growing repos surface too

- **Can it make money**: an AI commercial score, level and confidence per project; the six dimensions (pain point intensity, target-customer clarity, redevelopment feasibility, solo-buildability, monetization headroom, license friendliness) with their per-dimension evidence live **on the project page**, not in the API output

- **What to do next**: minimal viable product directions, target customers, and monetization models — on the project page; every skill output links straight there

- **Zero dependencies + local cache**: pure Python standard library; results are cached locally so repeated questions do not burn quota

**Who it is for**

- 🧑‍💻 **Indie developers / solopreneurs** — find open-source bases one person can actually productize

- 🔎 **Tech leads** — compare candidates on feasibility and license risk

- 📈 **Trend watchers** — see what is genuinely accelerating each week and month

- 🧭 **Idea hunters** — describe the problem and get a candidate shortlist

---

## Features

### Search

- **Semantic search (the only search entry point)**: hybrid retrieval (vector + full text) over natural-language problem statements, keywords, repo names and technical terms alike; narrow results with `--tag`

- No need to choose between "keyword search" and "semantic search": one entry point, one result set

### Rankings

- **Weekly growth**: top N by 7-day star velocity

- **Monthly growth**: top N by 30-day star velocity

- **Commercial value**: top N by six-dimension AI score

- All filterable by category; recomputed daily

### Project detail (summary) and comparison

- **Project detail**: stars / forks / issues, dual-window growth, license and risk level

- **Detail is a summary too**: the commercial score, level and assessment confidence are returned; the per-dimension scores and evidence are **not** — they live on the project page on opc.run

- **Alternatives**: no dedicated similar-projects endpoint — search again with the repo name / stack and let the agent compare the returned fields

- **Side-by-side comparison**: one table for all candidates (objective metrics + commercial score); per-dimension comparison means opening each project page

---

## API key and security

- Works without a key: **3 requests per day**

- With a key: quota follows your account plan, higher than the unregistered limit

- API keys are issued by [OPC.run](https://opc.run). Register at the [signup page](https://opc.run/app/passport?from=skill&return_url=%2Fapp%2Fprofile%2Fapi-keys) — you land on the [API Keys page](https://opc.run/app/profile/api-keys) right after signup

- Configure either way (on Windows, replace `python3` with `python` if the `python3` command is absent):

  ```bash

  python3 scripts/projects.py auth sk_xxxx...   # recommended: validate & save locally (chmod 600); --status to view / --clear to remove

  export OPCRUN_API_KEY="sk_xxxx..."            # environment variable (takes precedence over the local file)

  {"env":{"OPCRUN_API_KEY":"sk_xxxx..."}}       # env block of your agent config

  ```

- Before providing any key, verify its origin, scope, expiry, and whether it can be rotated or revoked

- Never hardcode or expose keys in code, prompts, logs, or output files

---

## Usage

Just describe what you need in natural language — no commands to memorize.

| Intent | Example | Result |
| --- | --- | --- |
| Find a solution | "A ticketing system one person can operate" | Semantic search with ranked candidates |
| Track trends | "What's gaining traction in AI this week" | Category-filtered weekly ranking |
| Monthly view | "Fastest-growing repos this month" | Site-wide monthly ranking |
| Money potential | "Open-source projects worth building a paid service on" | Commercial value ranking |
| Assess a repo | "Can owner/repo be commercialized?" | Commercial score + confidence as a summary, then a link to the full assessment and entry directions |
| Alternatives | "Projects like owner/repo" | Search again by repo name / stack; the agent compares the results |
| Pick one | "Which of A and B is easier to build on?" | Side-by-side comparison table |

### Sample output

> The script emits Chinese labels, so the block below is the **verbatim** output
> （`周/月` = 7-day / 30-day growth，`商业分` = commercial score，`查看详情页` = details page）.
> Keep it exactly as-is when composing an answer — including the `from=skill` parameter.

```markdown
### 语义检索：有没有适合一个人做的开源 AI Agent 框架（3 个）

**1. [langchain-ai/langgraph](https://opc.run/projects/langchain-ai-langgraph?from=skill)**
  ⭐ 21.0k ｜ 🔧 Python ｜ 📈 周 +420 / 月 +1,900 ｜ 💰 商业分 4.35 ｜ 📜 MIT
  Build resilient language agents as graphs.
  👉 [查看详情页：六维评估 · 增长曲线 · 变现建议](https://opc.run/projects/langchain-ai-langgraph?from=skill)

🔗 完整榜单与实时增长数据：[opc.run/projects](https://opc.run/projects?from=skill)

---

数据来源：OPC.run 开源精选 · [opc.run/projects](https://opc.run/projects?from=skill)
```

---

## Disclaimer

1. **Data & freshness**: metrics come from a daily snapshot of public GitHub data and may lag or drift. Always confirm stars, forks and growth on the official GitHub page.

2. **AI-generated content**: the commercial score, and the six-dimension assessment, reasoning, entry directions and monetization ideas shown on the project page, are AI-generated and provided for reference only. They are **not investment advice, not a basis for business decisions, and imply no promise of returns**.

3. **License is not legal advice**: license identifiers and risk levels are detected automatically and **do not constitute legal advice**. Read the full LICENSE yourself before any commercial use, and consult a professional when in doubt.

4. **Third-party, unofficial**: this skill is provided by OPC.run and has **no affiliation, authorization, partnership or endorsement relationship** with GitHub, Inc. Inclusion of a project is not a recommendation, nor a guarantee of its safety or legality.

5. **Trademark**: GitHub® is a trademark of GitHub, Inc., used solely to identify the data source.

6. **Your responsibility**: audit any third-party code you adopt. Consequences of use are borne by the user.

OPC.run may adjust quotas, change or discontinue the service at any time.

Full terms: <https://opc.run/about/terms>

---

## Data source

All data comes from [OPC.run Open Source Picks](https://opc.run/projects):

- Daily star / fork / issue snapshots

- Real 7-day and 30-day deltas with composite growth scores

- Six-dimension AI business assessment with confidence (per-dimension evidence and entry directions are shown on the project page)

Refreshed daily. Rankings are stable within the same day.
