# Super Brainstorm / opc-run-super-brainstorm

---

## Overview

Hand a question to a room of "people" — and get back a **meeting**, not an answer.

A normal AI chat is one voice talking to itself. Super Brainstorm picks the 3-5 mentors best matched to your question and lets them speak in turn, each with their own persona, mental models and decision rules. Later speakers hear the earlier ones, push back, and call on the next person.

**Core value**

- **Opinions collide**: one question, three genuinely different chains of reasoning — management, investing, product. The disagreement is the most useful part.

- **Not one AI wearing different hats**: each mentor's persona, signature mental models and decision criteria come from a separate knowledge page, so tone and standards of proof differ.

- **Discussion and conclusion are split**: the skill gives you the clash of views (the disagreement itself is the valuable part). At most 3 rounds, then it stops — and no round-table resolution. **The round-table resolution, follow-up questions and mid-discussion interruption all live on the site** — the skill is the appetiser, not the closing act.

- **Fetch it back any time**: every discussion has a `task_id` you can re-read later; with an API key you can also open the same discussion on the site and keep questioning the mentors.

- **Zero dependencies + local cache**: pure Python standard library, no pip install. Finished discussions are cached locally, so re-reading them costs no quota.

**Who it is for**

- 🧑‍💻 **Indie developers / solopreneurs** — when you decide alone, what you lack is not information but a few competing framings

- 🧭 **People at a fork** — quit or stay, hire or not, switch tracks or not

- 📊 **People making trade-offs** — who want to hear the opposition before committing

- 🤔 **People who are stuck** — and need someone to take the problem apart

---

## Features

### Run a discussion

- Submit a question; the system analyses it and seats the best-matched mentors

- 1–3 rounds supported (default 2). More rounds means more friction — and more time

- The discussion runs asynchronously (typically 1–3 minutes) but **you do not wait in the dark**: speeches are delivered one by one, so you can read mentor #1 while mentor #2 is still thinking. Polling runs every 5 seconds for the first 30 seconds, then every 3 seconds, and **does not consume quota**

### Results

- Every speech shown by round, with action/expression, round number and speaking order

- **No round-table resolution**: the discussion stops where the viewpoints clash. That gap is intentional — go to the site to see the round table converge on a conclusion

- Fetchable any time by `task_id`, including the partial speeches of a discussion still in progress; finished discussions are cached locally for 24 hours

### Roster

- See who is in the brainstorm (title / name / one-line bio). Read-only, no quota.

### With an API key

- **Higher quota**: 3 discussions a day anonymously (no points); with a key it follows your account plan, at **10 points per discussion** (same as starting a meeting on the site; refunded if the discussion fails)

- **The discussion follows your account**: you can open the same discussion on the site, keep questioning the mentors and let the round table produce its resolution. Without a key you can only fetch it back by `task_id`, on the same machine

### What the full on-site version adds

| | Skill | Full on-site version |
| --- | --- | --- |
| Mentors | 3-5 (depends on how complex the question is) | 5 |
| Rounds | at most 3 | unlimited (keep the discussion going round after round) |
| Round-table resolution | ✗ | ✓ converges into a conclusion and a next step |
| User intervention | ✗ | ✓ cut in any time; mentors ask you questions and wait for your reply |
| Resolution archive | ✗ | ✓ saved into your personal knowledge base |

---

## API key and security

- Works without a key: **3 discussions per day**, no points charged

- With a key: quota follows your account plan, higher than the unregistered limit

- **10 points per discussion** (the same as starting a meeting on the site). Charged only when a key is configured — anonymous use is free. A failed discussion (mentor recommendation failed / timeout) is **refunded automatically**: no output, no charge

- The bigger win with a key: **the discussion follows your account**, so you can open it on the site and keep questioning the mentors

- API keys are issued by [OPC.run](https://opc.run). Register at the [signup page](https://opc.run/app/passport?from=skill&return_url=%2Fapp%2Fsession%2Flist), then open **API Keys** from the left menu: [API Keys page](https://opc.run/app/profile/api-keys)

- Configure either way (on Windows, replace `python3` with `python` if the `python3` command is absent):

  ```bash

  python3 scripts/brainstorm.py auth sk_xxxx...   # recommended: validate & save locally (chmod 600); --status to view / --clear to remove

  export OPCRUN_API_KEY="sk_xxxx..."              # environment variable (takes precedence over the local file)

  {"env":{"OPCRUN_API_KEY":"sk_xxxx..."}}         # env block of your agent config

  ```

- Before providing any key, verify its origin, scope, expiry, and whether it can be rotated or revoked

- Never hardcode or expose keys in code, prompts, logs, or output files

---

## Usage

Just ask in natural language — no commands to memorize.

| Intent | Example | Result |
| --- | --- | --- |
| Make a call | "I run a cross-border e-commerce solo, $30k/month revenue — should I hire?" | A discussion with competing views (the resolution lives on the site) |
| Pick one | "Keep the job or go indie?" | Multi-perspective simulation that shows you where the views split |
| Assess risk | "How risky is going all-in on AI apps right now?" | Risk view crossed with opportunity-cost view |
| Re-read | "Show me that discussion again" | Fetched by `task_id` (no quota) |
| Roster | "Who is in the brainstorm?" | Read-only roster |
| Quota | "How many more can I run?" | Quota check (no quota) |

### Sample output

```markdown
### Super Brainstorm · Should a one-person company hire its first employee

**Question**: I run a cross-border e-commerce store solo, $30k/month revenue — should I hire now?

👥 **At the table**: Father of Modern Management (Peter Drucker) ｜ Investment Philosopher (Charlie Munger) ｜ Father of Apple (Steve Jobs)

#### Round 1

**Father of Modern Management** *( adjusts his glasses )*

Don't ask "should I hire" yet. Ask "what three things does your week actually go to"…

#### Round 2

**Investment Philosopher** *( pauses )*

I agree with the time audit. But I would add a harder test: …

Note: the discussion above is AI-generated and provided for reference only; it is not investment, legal or business advice.

💬 **1 mentor asked you a question** (the speech marked ❓ above) — only you can answer it; this skill cannot answer for you.
💡 **The discussion has finished, but there is no conclusion yet** — the mentors each gave their view and none of them produced a decisive recommendation. For a definite answer, or to keep talking, go to the site.
🚀 [On OPC.run](https://opc.run/app/session/list?from=skill) you can do more: more mentors, **unlimited rounds**, and **you can cut in at any time** — the mentors will stop and wait for your reply.
🔗 **[Sign in to keep talking about this discussion](https://opc.run/app/session/claim?t=6f1c...&from=skill)** — you land right back in it, and that 1 question is waiting for you there.
🔗 New here? [See what Super Brainstorm does](https://opc.run/session?from=skill)

Data source: OPC.run Super Brainstorm · [opc.run/session](https://opc.run/session?from=skill)
```

> The script emits Chinese labels; the block above is an **English rendering of the same shape**
> (see the verbatim output in [`references/output-examples.md`](references/output-examples.md)).
> The tail changes by identity: with an API key configured, the last link becomes
> "**[打开这场讨论]** — it is already in your brainstorm"; once claimed, no link is offered at all.

---

## Disclaimer

1. **AI-generated content**: mentor speeches, and the reasoning and round-table resolutions shown on the site, are AI-generated. They are **not investment advice, legal advice, medical advice, or a guarantee of any business decision**. Mentors are persona constructs built from public figures' methods and mental models; **they do not represent those individuals' own statements**, nor OPC.run's views.

2. **Not a substitute for professionals**: for legal, financial, tax, medical, HR-compliance or investment matters, consult a qualified professional. Do not treat this output as the sole basis for a decision.

3. **No promise of outcomes**: mentor speeches and round-table resolutions only move the discussion one step forward. They are **not a promise of any return, effect or result**.

4. **Data retention**: submitted questions and discussions are stored on OPC.run so you can continue them on the site and so we can analyse service quality. Do not submit classified information, personal data you must not disclose, or trade secrets you have no right to share.

5. **Your responsibility**: the consequences of decisions made on this basis are borne by the user. OPC.run may adjust quotas, change or discontinue the service at any time.

Full terms: <https://opc.run/about/terms>

---

## Data source and the full on-site version

- Mentor personas, mental models and skills come from OPC.run's public mentor knowledge layer (`wikis_pages` rows with `type=mentor`)

- Discussions are generated by the LLM at run time

- The **full on-site version** ([opc.run/session](https://opc.run/session?from=skill)) adds what the skill does not have: **five mentors**, **unlimited rounds**, round-table resolutions, mentors that ask *you* questions and wait for your reply (real back-and-forth, cut in any time), and resolutions written into your personal knowledge base

The skill is a lightweight taste. To grind on the same question, go to the site.
