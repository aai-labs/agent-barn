# AF-412 Task-keeping: behaviour and token cost against a baseline

Date: 2026-10-22. Environment: local k3d (`agentfarm-dev`) with the compose stack, LiteLLM
proxying `openrouter/qwen/qwen3.6-plus`, runtime images `agentfarm-hermes-base:0.2.10` and
`agentfarm-openclaw-base:0.7.7` built from the tested branch.

## What was compared

Five cohorts, each two Agents per runtime (Hermes and OpenClaw) from the `general-purpose` template with a $2
spend limit, all running the same 15-turn conversation through the dashboard chat:

| Cohort | Code | What the Agents had |
|---|---|---|
| baseline | AF-411, `edf3a199` | The Task store; no Task command, plugin or instructions. |
| treatment (round 1) | AF-412, `aea286d4` | The `agentbarn_task` tool and `agentbarn-tasks` plugin: a request line, open Tasks each turn, in-turn and next-turn reminders, automatic file attachment; Hermes tool search off. |
| optimised (round 2) | `4bea6213` | The plugin closes a Task left `in_progress` when the turn ends; `create` starts `in_progress` and takes a note; `attach --replace`; no request line on small talk; shorter instructions. |
| fixed (round 3) | `754f693d` | Also lists the three latest finished Tasks, so follow-ups reopen their Task; files carried to the next turns. |
| automatic (round 4) | `0d8e4a32` | The plugin records work the Agent left unrecorded as a Task with origin `automatic`, replacing the next-turn catch-up; Hermes background review and subagent runs are left alone. |

The baseline Agents were created while the API served the AF-411 code, so their configuration is AF-411's. The
first two cohorts ran concurrently; each later round ran on its own, on fresh Agents, after the previous round's
Agents were stopped. None of the pods restarted during a run.

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
No prompt caching was in effect (LiteLLM reported 0 cached tokens), so every call paid for its full context.

## Cost

Per Agent over the whole conversation, mean of two Agents:

| Cohort | Runtime | Input tokens | Cost (USD) | Model calls | Tool calls | of which Task |
|---|---|---|---|---|---|---|
| baseline | hermes | 1,232,438 | 0.413 | 39.0 | 21.0 | 0 |
| baseline | openclaw | 955,154 | 0.320 | 31.0 | 20.0 | 0 |
| treatment | hermes | 1,791,126 | 0.602 | 50.5 | 38.5 | 14.0 |
| treatment | openclaw | 1,767,030 | 0.589 | 49.0 | 40.5 | 15.0 |
| optimised | hermes | 1,490,754 | 0.499 | 46.5 | 28.0 | 7.0 |
| optimised | openclaw | 1,132,284 | 0.379 | 35.0 | 24.0 | 8.0 |
| fixed | hermes | 1,431,987 | 0.480 | 42.0 | 24.5 | 5.5 |
| fixed | openclaw | 1,696,030 | 0.564 | 44.0 | 34.5 | 7.5 |
| automatic | hermes | 1,533,276 | 0.517 | 47.0 | 29.0 | 4.5 |
| automatic | openclaw | 1,348,410 | 0.450 | 39.0 | 31.0 | 8.0 |

Input tokens against the baseline:

| Runtime | treatment | optimised | fixed | automatic | Rounds 2–4 pooled |
|---|---|---|---|---|---|
| hermes | +45% | +21% | +16% | +24% | +21% |
| openclaw | +85% | +19% | +78% | +41% | +46% |

In round 1, about two thirds of the overhead was extra model round trips for Task tool calls (create, status,
attach), each re-sending the whole context, and one third the larger context on every call. Rounds 2–4 halve the
Task calls or better (14–15 per conversation down to 4.5–8): closing, attaching and recording missed work are done by
the plugin without a model call.

The later rounds swing more than the Task calls explain. Work tool calls, the ones that are not Task calls, varied
from 16 to 27 per OpenClaw Agent between rounds, and one OpenClaw Agent in round 3 made 11 web calls on the research
turn and spent 482k tokens on the first offsite turn; every later turn re-sends that history. With two Agents per
cell, that variance is larger than the Task overhead itself, so the pooled figure is the better estimate.

## Task behaviour

| Cohort | Agent | Tasks | Files attached | Notes | Recorded automatically |
|---|---|---|---|---|---|
| treatment | T-hermes-1 / -2 | 6 / 7 | 6 / 6 | 1 / 0 | n/a |
| treatment | T-openclaw-1 / -2 | 8 / 7 | 5 / 5 | 0 / 0 | n/a |
| optimised | O-hermes-1 / -2 | 7 / 6 | 3 / 5 | 3 / 5 | n/a |
| optimised | O-openclaw-1 / -2 | 8 / 5 | 4 / 4 | 2 / 2 | n/a |
| fixed | F-hermes-1 / -2 | 5 / 3 | 4 / 3 | 3 / 0 | n/a |
| fixed | F-openclaw-1 / -2 | 5 / 6 | 4 / 4 | 0 / 0 | n/a |
| automatic | A-hermes-1 / -2 | 5 / 6 | 4 / 5 | 1 / 0 | 1 / 4 |
| automatic | A-openclaw-1 / -2 | 6 / 6 | 4 / 4 | 0 / 0 | 0 / 0 |

- **Round 1** recorded every piece of work, but OpenClaw also made Tasks for a rename and touched Tasks on small
  talk and a quick fact. One file reworked over two turns was attached twice.
- **Round 2** recorded work, but follow-ups produced empty duplicate Tasks: the closed Task was no longer listed, the
  follow-up edit went unrecorded, and the next-turn catch-up created a new Task without the file. On Hermes the
  Task was sometimes created by Hermes's own background review run, which follows the turn in the same session and
  never saw the files.
- **Round 3** removed the duplicates: follow-ups reopened the Task they continued. One Hermes Agent ignored both the
  in-turn and the next-turn reminders and recorded only three of its jobs.
- **Round 4** recorded every job on all four Agents. One Hermes Agent recorded two of its six Tasks itself; the
  plugin recorded the other four, titled with the user's request and with their files attached. The OpenClaw Agents
  needed no automatic Task. Turns below the work threshold (the Hermes rename, the impossible booking) have no Task,
  as intended.

Small talk stopped producing Task calls from round 2. Replies occasionally mention Tasks (two or three per cohort,
mostly a turn-1 capability list); this is tolerated.

## Findings

1. **Task-keeping works and every job is recorded.** With automatic recording, work the Agent leaves unrecorded is
   still captured, labelled `automatic` so it can be told apart from Tasks the Agent wrote.
2. **The reminders are a nudge, not a guarantee.** In round 3 one Hermes Agent ignored both reminders for three jobs;
   automatic recording is what closes that gap.
3. **The cost of Task-keeping is roughly +20% input tokens on Hermes and +45% on OpenClaw**, down from +45% and +85%,
   at this model's prices about $0.09 and $0.14 per 15 turns. Most of what remains is the per-turn context (tool
   schema, instructions, request line, the Task list) and one or two Task calls per job.
4. **Notes stay rare.** Tasks show what was done and its output, not the steps.

## Limitations

Two Agents per cell, one model, one scripted conversation, and no prompt caching. The cost ratios depend on how large
the Agent's base context is relative to the Task overhead, and on how much work the model chooses to do; a model with
prompt caching would pay much less for the repeated context. One Hermes research turn in round 4 timed out (over seven
minutes of web calls, no Task calls); its work was still recorded automatically.
