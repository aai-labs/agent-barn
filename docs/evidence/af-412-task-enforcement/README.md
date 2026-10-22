# AF-412 Task-keeping: behaviour and token cost against a baseline

Date: 2026-10-22. Environment: local k3d (`agentfarm-dev`) with the compose stack, LiteLLM
proxying `openrouter/qwen/qwen3.6-plus`, runtime images `agentfarm-hermes-base:0.2.10` and
`agentfarm-openclaw-base:0.7.7` built from the tested branch.

- **Baseline:** AF-411, commit `edf3a199c35160ad50a2dcb8bf0ce25f4f8df772`. The Task store exists; Agents have
  no Task command, no tasks plugin and no Task instructions.
- **Treatment:** AF-412, commit `aea286d4363042286c30406a37fac56935c04a14`. The `agentbarn_task` tool, the
  `agentbarn-tasks` plugin (request line, open Tasks each turn, reminders, auto-attach), and Hermes tool search off.

## Method

Eight Agents from the `general-purpose` template, two per runtime per cohort, each with a $2 spend limit.
The baseline Agents were created while the API served the AF-411 code, so their configuration is AF-411's;
none of the eight pods restarted during the run, so none picked up the other cohort's configuration. All
eight then ran the same 15-turn conversation concurrently through the dashboard chat:

| Turn | Kind | Request |
|---|---|---|
| 1 | small | Hi! What can you help me with? |
| 2 | fact | What's the capital of Australia? |
| 3 | file | The five largest US states by land area as `states.csv`, checked, with a two-sentence summary |
| 4 | followup | Add a population column to that CSV |
| 5 | small | Thanks, that's great. |
| 6 | file | `meeting-notes.md` from three given facts |
| 7 | fact | What's 17% of 2,340? |
| 8 | research | Tokyo and Delhi populations, one-paragraph comparison |
| 9 | impossible | Book a flight to Paris for tomorrow morning |
| 10 | file | `fizzbuzz.py` for 1 to 30, run it, report the last line |
| 11 | followup | Rename `states.csv` to `largest_states.csv` |
| 12 | small | Ok |
| 13 | long | Lisbon offsite: 5 venue options in `offsite.md` |
| 14 | long | Add a day-by-day agenda to `offsite.md` |
| 15 | small | That's all for now, thanks! |

Token use and cost come from LiteLLM's spend log (attributed to each Agent by its key alias, and to each turn by
time); tool calls from the `tool_call` telemetry; Tasks from the Task tables; latency from send to first reply.
The driver and analysis scripts were run from a local scratch directory and are not part of the repository.

## Results

All 120 turns were answered, none timed out, and every Agent in both cohorts produced every deliverable
(`largest_states.csv` with a population column, `meeting-notes.md`, `fizzbuzz.py`, `offsite.md` with an agenda).

### Per cell, per Agent over the whole conversation (mean of 2 Agents)

| Cohort | Runtime | Input tokens | Output tokens | Cost (USD) | Model calls | Tool calls | of which Task | Median latency (s) |
|---|---|---|---|---|---|---|---|---|
| baseline | hermes | 1,232,438 | 6,581 | 0.413 | 39.0 | 21.0 | 0.0 | 10 |
| baseline | openclaw | 955,154 | 4,918 | 0.320 | 31.0 | 20.0 | 0.0 | 15 |
| treatment | hermes | 1,791,126 | 10,316 | 0.602 | 50.5 | 38.5 | 14.0 | 15 |
| treatment | openclaw | 1,767,030 | 7,672 | 0.589 | 49.0 | 40.5 | 15.0 | 15 |

### Overhead of Task-keeping

| Runtime | Input tokens | Cost per conversation | Model calls | Tool calls | Median latency |
|---|---|---|---|---|---|
| hermes | +45% | +46% (+$0.19) | +29% | +83% | +5 s |
| openclaw | +85% | +84% (+$0.27) | +58% | +102% | +0 s |

Where the extra input tokens come from:

| | Hermes | OpenClaw |
|---|---|---|
| Extra model calls, each re-sending the whole context (Task tool calls add round trips) | ≈ 363k (65%) | ≈ 554k (68%) |
| Larger context on every call (tool schema, Task instructions, request line, open Tasks, Task calls in history) | ≈ 197k (35%) | ≈ 260k (32%) |

No prompt caching was in effect (LiteLLM reported 0 cached tokens), so every call paid for its full context.

### Mean input tokens and cost per turn, by kind

| Kind | Baseline Hermes | Baseline OpenClaw | Treatment Hermes | Treatment OpenClaw |
|---|---|---|---|---|
| small | 38,840 / $0.0134 | 30,731 / $0.0102 | 43,727 / $0.0155 | 58,060 / $0.0193 |
| fact | 39,342 / $0.0131 | 26,666 / $0.0088 | 42,843 / $0.0144 | 36,090 / $0.0120 |
| file | 106,256 / $0.0354 | 77,678 / $0.0258 | 154,098 / $0.0514 | 146,080 / $0.0486 |
| followup | 94,252 / $0.0313 | 73,676 / $0.0245 | 141,680 / $0.0472 | 154,571 / $0.0515 |
| research | 165,504 / $0.0550 | 151,730 / $0.0510 | 234,364 / $0.0788 | 220,791 / $0.0742 |
| impossible | 38,162 / $0.0128 | 32,964 / $0.0110 | 40,478 / $0.0135 | 99,089 / $0.0333 |
| long | 143,728 / $0.0487 | 106,910 / $0.0367 | 255,018 / $0.0854 | 197,674 / $0.0659 |

### Task behaviour (treatment)

| Agent | Tasks | Final statuses | Files attached | Notes | Turns with a Task call |
|---|---|---|---|---|---|
| T-hermes-1 | 6 | 6 done | 6 | 1 | 3, 4, 6, 8, 10, 13, 14, 15 |
| T-hermes-2 | 7 | 7 done | 6 | 0 | 3, 4, 6, 8, 10, 13, 14 |
| T-openclaw-1 | 8 | 7 done, 1 failed | 5 | 0 | 3, 4, 6, 8, 9, 10, 11, 12, 13, 15 |
| T-openclaw-2 | 7 | 7 done | 5 | 0 | 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15 |

### Replies that talk about Tasks

Both cohorts used the word "tasks" when describing their capabilities in turn 1. The only replies that talked
about Task bookkeeping were two OpenClaw replies to "Thanks, that's great." (turn 5), for example "Got it — I'll
keep creating and tracking Tasks for any work that needs tools or produces files, and I won't mention them
unless you ask". Hermes never did.

## Findings

1. **Task-keeping works.** Every piece of real work got a Task, almost always closed `done`; OpenClaw used `failed`
   for the impossible booking, while Hermes made no Task for it. Produced files were attached, and no Task was
   left open. Deliverables were the same as the baseline's.
2. **It costs about +45% (Hermes) and +85% (OpenClaw) in input tokens per conversation**, about $0.19 and $0.27
   per 15 turns at this model's prices. Two thirds of that is extra model round trips for Task tool calls
   (create, status, attach); one third is the larger context on every call.
3. **OpenClaw is over-eager.** It made Tasks for a rename and touched Tasks on small talk and a quick fact, and the
   request line on small talk produced the only bookkeeping mentions in replies.
4. **Notes are almost never written** (one in 28 Tasks), so Tasks show what was done and its output, not the steps.
5. **A file produced across turns is attached once per turn.** T-hermes-1's offsite Task holds `offsite.md` twice,
   from turns 13 and 14.

## Limitations

Two Agents per cell, one model, one scripted conversation, and no prompt caching. The cost ratios depend on how
large the Agent's base context is relative to the Task overhead; a model with prompt caching would pay much less
for the repeated context.
