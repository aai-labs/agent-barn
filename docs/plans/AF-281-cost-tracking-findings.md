# Cost Tracking: Root Cause and Findings

**Date:** 2026-09-02
**Author:** Samuel Birhanu
**Scope:** Why agent cost tracking under-reported actual spend, what fixed it, and what is still broken.
**Status:** Root cause identified, independently reproduced, and confirmed catalog-independent. Primary defect already fixed in production by **AF-233** (Ananiya, `75204002`). Scope and priorities agreed with the team lead on 2026-09-02; secondary defects open.
**Implemented by:** AF-281. The defects below are addressed by the `cost_record` table, the cost sync and healing CronJob, and the org and platform cost pages. This document is kept as the evidence behind those decisions and describes the system as it was during the investigation; `docs/features/costs.md` describes it as it is now.

**Prior work:** AF-233 identified and fixed the LiteLLM defect. This document independently reproduces it, quantifies the loss over the affected window, and covers what AF-233 did not: the surrounding defects that let a 100% under-count go unnoticed for three months.

---

## Summary

During the affected window, production recorded **about a quarter of what it actually spent** ($110.52 logged against ~$424 actual). The cause was a single defect in LiteLLM, not in our code: versions at or below `v1.83.14` **discarded the per-request cost that OpenRouter returns on streamed responses**. Token counts were still logged, so the data looked healthy — busy request logs, billions of tokens, and almost no money.

Ananiya diagnosed this and shipped the fix as **AF-233** (`75204002`, 2026-08-14), upgrading LiteLLM `main-v1.83.14-stable.patch.3` → `v1.96.2`; it reached production on **2026-08-17T19:31Z**. Cost attribution has been accurate since.

What went unnoticed was not the fix but the **scale and duration of the breakage**: nothing in the product distinguishes "this cost nothing" from "we failed to record what this cost," so the three-month window and its ~$312 of unrecorded spend were never quantified, and the same blind spot remains today.

The pricing engine is no longer the problem. The problem is that **we cannot tell when it breaks**.

### The numbers

| | Pre-upgrade | Post-upgrade |
|---|---|---|
| Window | 2026-05-17 → 2026-08-17 | 2026-08-17 → 2026-09-01 |
| Requests | 29,096 | 10,737 |
| Tokens | 1,483,284,034 | 683,583,089 |
| Recorded spend | $110.52 | $187.31 |
| **Effective rate** | **$0.0745 / Mtok** | **$0.2740 / Mtok** |

Isolating the platform default model, `openrouter/z-ai/glm-5.2` (successful requests only), removes the mix effect and shows the defect cleanly:

| era | requests | tokens | recorded spend | $/Mtok |
|---|---|---|---|---|
| pre-upgrade | 19,042 | 1,154,525,203 | **$2.8594** | **$0.0025** |
| post-upgrade | 9,628 | 650,881,610 | **$176.2959** | **$0.2709** |

**A 108× difference in effective rate for the same model.** Pricing did not change; recording did.

**Unbilled: ~$313 in production, ~$12 in staging.** 19,135 production requests carrying 1,157,582,125 tokens were logged at exactly $0.00, plus 1,277 staging requests carrying 49,092,925 tokens. Valued at each environment's own post-upgrade rate, that is ~$313.54 and ~$12.32 of real spend written to the database as zero.

**These rows are recoverable.** Every one of them carries an OpenRouter generation ID in `request_id`, and OpenRouter still serves the exact cost for them — see [Backfill](#backfill-is-possible-and-exact).

---

## Root cause

### How pricing is supposed to work

`docker/litellm/config.yaml` and `helm/litellm/templates/configmap.yaml` route all traffic through a single wildcard:

```yaml
- model_name: "openrouter/*"
  litellm_params:
    model: "openrouter/*"
```

This is deliberate — the model catalogue is driven by OpenRouter rather than a hand-maintained list. The consequence is that **LiteLLM's static price map cannot price our traffic**, and never could. Verified against the live map fetched from GitHub today:

```
model_prices_and_context_window.json : 3,408 entries, of which 100 are openrouter/*
  openrouter/z-ai/glm-5.2             MISSING
  openrouter/google/gemini-3.6-flash  MISSING
  openrouter/openai/gpt-4o-mini       MISSING
```

`litellm.cost_per_token(model="openrouter/z-ai/glm-5.2", ...)` raises `This model isn't mapped yet`. The static map covers under 3% of OpenRouter and does not include the model we default to.

So the **only** viable pricing path is the cost OpenRouter reports per request. LiteLLM asks for it in `llms/openrouter/chat/transformation.py`:

```python
# ALWAYS add usage parameter to get cost data from OpenRouter
if "usage" not in response:
    response["usage"] = {"include": True}
```

and harvests it in `transform_response`:

```python
response_json = raw_response.json()
response_cost = response_json["usage"].get("cost")
...
model_response._hidden_params["additional_headers"]["llm_provider-x-litellm-response-cost"] = float(response_cost)
```

`transform_response` only runs for a **whole-body** response. It is never reached for a streamed one.

### The defect

`OpenRouterChatCompletionStreamingHandler.chunk_parser` — the streaming path — forwards `usage` through but contains **no cost handling at all**. This is true in `v1.83.14` and remains true in `v1.96.2` and on upstream `main` today.

The actual fix lives in a different file. `litellm_core_utils/streaming_handler.py` in `v1.96.2` contains a method absent from `v1.83.14`:

```python
@staticmethod
def _propagate_usage_cost_to_hidden_params(response) -> None:
    """If the assembled response carries a provider-reported cost on
    usage.cost, copy it into _hidden_params so litellm's cost
    calculator uses it instead of a token-based estimate."""
    _usage = getattr(response, "usage", None)
    if _usage is not None and hasattr(_usage, "cost") and _usage.cost is not None:
        ...
        response._hidden_params["additional_headers"]["llm_provider-x-litellm-response-cost"] = float(_usage.cost)
```

`grep -rl "llm_provider-x-litellm-response-cost"` lists `streaming_handler.py` in `v1.96.2` and not in `v1.83.14`. That one file is the entire difference.

**Why the cost chunk never arrived.** Per the AF-233 commit message, OpenRouter emits its usage chunk — the one carrying `cost` — *after* the `finish_reason` chunk. The old stream handler raised `StopIteration` on the first chunk following `finish_reason`, so the usage chunk was never folded into the assembled response. Cost then fell back to a token-based estimate, which is zero for any model absent from the bundled price map — that is, every model we route.

Upstream fix: [BerriAI/litellm#32255](https://github.com/BerriAI/litellm/pull/32255), first shipped in **v1.94.0**. Anything at or below v1.93.x has this defect.

**Net effect on the old version:** every streamed request through the wildcard route had no static price and no captured cost, so it was booked at $0.00 while its locally-counted tokens were recorded normally. Agent traffic is overwhelmingly streamed, which is why the loss approaches total.

---

## Reproduction

Reproduced end to end on the local k3d environment. Identical prompt, identical model, identical `max_tokens`, same virtual key throughout — the only variables are `stream` and the LiteLLM version.

| # | LiteLLM version | mode | prompt/compl/total | recorded spend |
|---|---|---|---|---|
| 1 | v1.83.14 | non-streaming | 19 / 16 / 35 | **$0.0000485** |
| 2 | v1.83.14 | streaming | 19 / 16 / 35 | **$0.000000** |
| 3 | v1.83.14 | streaming + `stream_options.include_usage` | 19 / 16 / 35 | **$0.000000** |
| 4 | v1.96.2 | non-streaming | 19 / 16 / 35 | **$0.0000485** |
| 5 | v1.96.2 | **streaming** | 19 / 16 / 35 | **$0.0000485** |

Token counts are identical across all five. Only the money moves.

Row 3 matters: asking for usage explicitly makes the stream carry correct token counts but **no `cost` field**, so it is not a workaround on the old version.

The data was always on the wire. Calling OpenRouter directly, bypassing LiteLLM, with `stream: true` and `usage: {include: true}`:

```json
"usage":{"prompt_tokens":19,"completion_tokens":16,"total_tokens":35,
         "cost":0.0000485,
         "cost_details":{"upstream_inference_cost":0.0000485, ...}}
```

OpenRouter reports cost on streams. LiteLLM ≤ v1.83 simply dropped it.

---

## Current state

Since the upgrade, the leak is effectively closed:

| bucket | requests | tokens | spend |
|---|---|---|---|
| priced | 10,213 | 680,669,331 | $186.90 |
| zero | 474 | 1,681,782 | $0.00 |

**0.25% of tokens unbilled**, against ~48% of all-time requests before.

Breaking down the 474 zero rows:

| status | model | reqs | tokens |
|---|---|---|---|
| success | `openrouter/z-ai/glm-5.2` | **19** | **1,681,247** |
| failure | `openrouter/z-ai/glm-5.2` | 389 | 535 |
| failure | `openrouter/qwen/qwen3.6-plus` | 41 | 0 |
| failure | `openrouter/ai21/jamba-large-1.7` | 19 | 0 |
| failure | `openrouter/openai/gpt-5-mini` | 4 | 0 |
| failure | `qwen3.6-plus` | 2 | 0 |

**455 of 474 are failed requests carrying no tokens** — correctly $0. Only 19 rows are a real leak, and they share an unambiguous signature:

| | priced | zero-spend |
|---|---|---|
| requests | 10,213 | 19 |
| `completion_tokens = 0` | **0 (0.0%)** | **8 (42.1%)** |
| avg prompt tokens | 66,018 | 88,144 |
| avg duration | 10.8 s | **57.6 s** |

Zero of 10,213 priced requests have an empty completion; 42% of the leaking ones do, and they run 5.3× longer (individual durations of 196 s, 175 s, 164 s, 136 s). These are long, large-context requests whose stream ended before OpenRouter delivered the final chunk carrying `cost` — the same mechanism as the original bug, now triggered by truncation rather than by version.

**Residual unbilled: $2.02** (1,674,731 prompt + 6,516 completion tokens at catalogue rates), or 1.1% of recorded spend. Worth a ticket, not urgency.

> **Correction to earlier analysis.** `google/gemini-3.6-flash`, `poolside/laguna-s-2.1`, `qwen/qwen-plus` and `openai/gpt-4o-mini` were previously reported as *currently* recording $0. That was read from lifetime totals and is wrong. None appear among post-upgrade zero rows; all of that traffic predates the upgrade and is already explained. **There is no live per-model pricing hole.**

---

## The catalog no longer determines cost tracking

A natural worry after this incident is that adding a new model will silently break tracking again — that was the pre-upgrade failure mode. **It no longer applies.** Verified empirically on both eras.

### Post-upgrade: provider-reported cost wins, catalog is ignored

`gryphe/mythomax-l2-13b` is the discriminator: it **is** in the v1.96.2 catalog, and that catalog entry is 31x wrong.

| model | in catalog | catalog predicts | OpenRouter reports | **LiteLLM records** |
|---|---|---|---|---|
| `gryphe/mythomax-l2-13b` | **yes** | $0.00015563 | $0.00000498 | **$0.00000498** |
| `z-ai/glm-5.2` | no | — (would be $0) | $0.00014460 | **$0.00014460** |
| `tencent/hy4-preview` | no | — (would be $0) | $0.00014590 | **$0.00014590** |
| `inception/mercury-2.5-preview` | no | — (would be $0) | $0.00000736 | **$0.00000736** |

Every recorded value matches OpenRouter to the cent. Where a catalog entry existed and disagreed, it was ignored.

### Pre-upgrade: the catalog was the only source

From production's own pre-upgrade rows, recorded spend reproduces the catalog computation exactly:

| model (pre-upgrade, spend > 0) | reqs | recorded | catalog | OpenRouter | source |
|---|---|---|---|---|---|
| `qwen/qwen3.6-plus` | 7,858 | $105.5862 | $105.5862 | $105.5862 | catalog |
| `anthropic/claude-3-haiku` | 63 | $0.4194 | $0.4194 | $0.4194 | catalog |
| **`deepseek/deepseek-chat`** | 4 | **$0.0064** | **$0.0064** | **$0.0120** | **catalog** |

`deepseek-chat` settles it — catalog and OpenRouter disagree, and the recorded figure is the catalog's.

### The rule in each era

| | pre-upgrade (<= v1.83) | post-upgrade (>= v1.94) |
|---|---|---|
| model **in** catalog | priced from catalog — wrong whenever the catalog is stale | priced from OpenRouter; catalog ignored |
| model **absent** from catalog | **$0.00** | priced from OpenRouter |
| new model added | **silently untracked** | works with no action |
| catalog accuracy | determines correctness | irrelevant |

The v1.96.2 catalog holds 2,981 entries, of which only 95 are `openrouter/*`; **290 paid OpenRouter models are absent from it entirely.** Before AF-233 every one of them would have recorded $0. All of them record correctly now.

A secondary consequence: pre-upgrade data is not only wrong where it is zero. Where the catalog was stale the non-zero figures are wrong too — `deepseek-chat` was billed at 53% of actual. In aggregate that error is negligible (~$0.006, because 95% of pre-upgrade spend was `qwen3.6-plus`, whose catalog price happened to be correct), but it means healing should work **per generation ID**, not merely target the zeros.

---

## Secondary defects

These did not cause the loss, but they are why it went unnoticed for three months — and they will hide the next one.

### 1. The Costs page reports failure as $0.00

`api/infrastructure/litellm/client.py`, `get_global_spend_report()` catches every exception and returns `{}`:

```python
except Exception as exc:
    logger.warning("Failed to fetch aggregated daily activity: %s", exc)
    return {}
```

An empty dict renders as a confident **$0.00** with no error state. A LiteLLM outage, an auth failure, a schema change, and a genuinely idle organization are indistinguishable in the UI. **This is the single highest-value fix in this document** — not because it loses money, but because it is the reason a 100% under-count was invisible.

### 2. Virtual keys carry no budget

`generate_key()` sets only `key_alias` and `metadata`. Confirmed against a freshly minted key:

```
max_budget=None  budget_duration=None  tpm_limit=None  rpm_limit=None  user_id=None  team_id=None
```

No per-agent ceiling, no rate limit, no team rollup. A runaway agent is bounded only by the OpenRouter key's own limit.

### 3. Cache tokens are discarded — accepted as a known gap

**Decision: not in scope. Documented here so the gap is deliberate rather than accidental.**

LiteLLM records **614,406,925 `cache_read_input_tokens`** against 2,201,874,681 prompt tokens — **28% of all input** — in `LiteLLM_DailyUserSpend`. `api/domains/costs/models.py` has no field for them, so they never reach the API or the UI.

**This is not a billing-accuracy problem.** OpenRouter's reported `cost`, which is what we record, already has the cache discount applied. Totals are correct. What is missing is the ability to *explain* them.

**What caching is worth to us.** Providers cache the prompt prefix — system prompt, tool definitions, conversation history — and charge a fraction of the normal input rate when the next request reuses it. Agents resend their whole history every turn, so the prefix is nearly the entire prompt:

| model | fresh input | cache read | cache write |
|---|---|---|---|
| `z-ai/glm-5.2` | $0.9660/M | **$0.1932/M (20%)** | not published |
| `anthropic/claude-3-haiku` | $0.2500/M | **$0.0300/M (12%)** | $0.3000/M (**120%**) |
| `qwen/qwen3.6-plus` | $0.3250/M | not published | $0.4062/M (**125%**) |

At glm-5.2 rates those 614M cache-read tokens cost roughly **$119 instead of $593 — about $474 saved**, more than our entire recorded spend. Rough, since the model mix varies, but the order of magnitude holds.

**Two distinct caches, easily confused.** The per-call `cache_hit` field on spend log rows refers to **LiteLLM's own response cache**, not the provider's prompt cache. Proof from production: `cache_hit` is `False` on all 38,876 rows and `None` on 1,684 — **never true**, because we run no proxy cache — while the daily rollup simultaneously records 614M cache-read tokens. `cache_hit` would therefore tell us nothing about prompt caching even if it were populated.

**Available at exactly one resolution.** Cache token counts exist only in the daily rollup — per day, per key, per model. Every LiteLLM variant is daily (`/user/`, `/team/`, `/organization/`, `/agent/`, `/customer/`, `/tag/daily/activity`); the only extra knob is a `timezone` integer that shifts day boundaries, not granularity. There is **no per-request attribution and no sub-daily option**, so a per-request cache column cannot be built at all.

**What we give up by not tracking it.** A prompt cache is fragile: changing anything early in the prompt — a system prompt edit, reordered tool definitions, an injected timestamp — invalidates the prefix, and every request reverts to full price. **Token counts stay identical while cost multiplies roughly 5x.** That regression is invisible in every metric we currently surface, and would only be detectable as a shift in the daily cache-read ratio. Accepting this gap means accepting that a 5x cost event of this kind would be found by noticing the bill, not by an alert.

**If revisited**, the smallest useful version is a supplementary pull of `/user/daily/activity/aggregated` in phase 1 of the sync job — one extra call per window and one column pair — giving a daily cache-hit ratio per organization. It is cheap to add now and awkward to retrofit once the table is in production.

### 4. Attribution orphans on agent deletion

Of 84 virtual keys with non-zero spend, **59 reference an `agent_id` with no matching row** in the application database. That is **$9.48, or 3.3%** of recorded spend that cannot be attributed to any agent. `docs/features/costs.md` states the invariant that soft-deleted agents remain attributable; hard-deleted ones evidently do not.

### 5. Per-agent and organization views disagree by construction

`get_agent_cost()` reads `/key/info`, which returns **lifetime** spend and ignores the date range. `get_org_cost_summary()` uses date-ranged aggregation. The two endpoints answer different questions and will not reconcile for any window shorter than the agent's lifetime.

### 6. Failures are invisible

**1,880 failed requests** lifetime. The aggregated payload exposes `failed_requests`, and we surface none of it. Agents fail silently as far as the Costs UI is concerned.

### 7. Local dev ran 13 minor versions behind production

AF-233 bumped `helm/litellm/values.yaml` to `v1.96.2` but left `compose.yml` on `main-v1.83.14-stable.patch.3`. The same version is pinned in two places and only one was updated, so local development kept reproducing the *broken* behaviour for three weeks after production was fixed.

Anyone investigating cost locally in that window would have concluded production was still broken, or validated a fix against a baseline that already had the bug. Bumping this pin to match production is included in the accompanying change.

### 8. Local development spends production credit

Production, staging and local development all authenticate with the **same** OpenRouter key. Verified by hash: the key in the local `.env`, in the production `litellm` secret, and in the `agent-farm-staging` `litellm` secret are byte-identical (`sha256[:16] = b5cbedd74ac8604c`).

One key means one pooled usage figure covering three environments, while each LiteLLM database sees only its own slice. Reconciling recorded spend against OpenRouter is therefore impossible today.

**Staging had the same defect and the same fix.** Its LiteLLM moved to `v1.96.2` on 2026-08-17T17:35Z, two hours before production:

| staging era | requests | tokens | recorded |
|---|---|---|---|
| pre-upgrade | 1,545 | 51,080,995 | $0.8792 |
| post-upgrade | 408 | 13,733,570 | $3.4477 |

A 4x jump in recorded spend on a third of the requests — the same signature as production.

**The full picture reconciles to 87%:**

| | $ |
|---|---|
| prod recorded | 306.29 |
| staging recorded | 4.33 |
| prod invisible (est. @ $0.2709/Mtok) | 313.54 |
| staging invisible (est. @ $0.2510/Mtok) | 12.32 |
| **= accounted for** | **636.48** |
| OpenRouter key lifetime usage | 730.97 |
| **unexplained residual** | **94.49 (13%)** |

The residual is almost certainly **local development**, and it is unmeasurable by construction: local LiteLLM databases live in disposable Docker volumes on developer machines. Every local agent run for the past four months billed to the production key and left no queryable trace.

Two things follow. The ~$313 estimate is corroborated — the equation closes to 13% with only the untrackable term missing. And splitting the key is not hygiene but a hard prerequisite: 13% of a $731 bill currently has no owner and no ledger.

Account-level position: `total_credits: 2450`, `total_usage: 2323.30`.

---

## Decisions (team lead, 2026-09-02)

Resolved in DM with Kalkidan Betre:

| Question | Decision |
|---|---|
| Backfill or document the hole? | **Backfill — mandatory.** A live client (GG Media Group) is already running on this data. Corrected figures must be per-organization, not just a corrected total. |
| One-time or ongoing? | **Ongoing "data healing"**, not a one-off script. |
| Infrastructure cost in scope? | **No.** All cost is OpenRouter model consumption. |
| What does "platform cost" mean? | A **platform-admin cost view**: total spend across the platform, broken down per organization, alongside the existing per-org view. |
| UI shape | Model it on the **Event Delivery Monitor** (AF-247): summary stat cards, server-side search/filters/date range, an infinite-scroll table via TanStack Query — **and keep the existing charts**. |

### What the UI decision implies

The platform view is a sibling of an existing surface, not new ground. [`api/domains/events/routes.py`](api/domains/events/routes.py) already implements the pattern: prefix `/platform/event-deliveries`, every route gated by `require_platform_admin()`, `PaginatedItems[T]` with `page`/`page_size`, and a filter model resolved through a dependency. The UI lives at [`ui/src/app/dashboard/platform/event-deliveries`](ui/src/app/dashboard/platform/event-deliveries) with the feature split into `hooks/` and `components/`. A `/platform/costs` surface reuses all of it; `require_platform_admin` already exists in `api/domains/auth/utils.py`, so no new RBAC concept is needed.

**This makes the table we own a hard requirement rather than a recommendation.** Server-side filtering and pagination need `WHERE`/`LIMIT`/`OFFSET` over indexed columns. LiteLLM's `/user/daily/activity/aggregated` is explicitly non-paginated and returns the whole window in one payload — nothing in the requested mockup can be built on it. It also raises the weight of denormalizing `organization_id` at write time: that is the column the platform view groups by.

### UI specification

Two pages, **visually similar**, differing only in scope and one filter:

| | Org costs | Platform costs |
|---|---|---|
| route | `ui/src/app/dashboard/[orgId]/costs` (rebuilt) | `ui/src/app/dashboard/platform/costs` (new) |
| authorisation | existing `cost.read` (org owner/admin; platform admin bypasses) | `require_platform_admin()` |
| filters | agent, model | agent, model, **organization** |

**Components — reused from the current dashboard:** `Total Spend`, `Active Agents`, `Top Model`, `Cost Over Time`. All four exist today in `ui/src/features/costs/components/costs-dashboard.tsx` and are retained per the team lead ("and ofc we keep the charts as well").

**New:** a table of individual LLM calls with their cost, rendered with TanStack infinite query over server-side filters and search — the pattern from the Event Delivery Monitor.

**Every component is filter-aware.** The stat cards, the chart and the table all reflect the active filters, not just the table. This is a change of contract: `get_org_cost_summary()` currently accepts only `start_date`/`end_date`, so the summary endpoint must take the same filter parameters as the row endpoint and aggregate under them.

**Filters cascade.** Selecting an organization scopes the values offered by the agent and model filters to what exists within that organization. The filter-option endpoints must therefore be scoped themselves (e.g. `?organization_id=`), not static lists.

**The agent filter is searchable**, following `ui/src/features/event-deliveries/components/event-delivery-organization-combobox.tsx`. Agents render as **"agent_name in org_name"**, which means the cost row must carry the agent's display name and the organization's name — reinforcing the decision to denormalize identity at write time rather than joining at read time (see [What the deletion decision requires](#what-the-deletion-decision-requires)).

### Additional metrics

**The cost driver is input, not output.** Across the lifetime, 2,146,536,517 prompt tokens against 20,330,606 completion tokens — output is **0.94%** of volume — and the average request carries **64,428 prompt tokens**. Spend is therefore governed by how much context is resent on every call, not by how much agents produce. That is why "avg prompt tokens per call" is a headline metric below rather than a detail: it is the number that maps to an action (trim the system prompt, prune history, cut tool definitions).

**Agreed for the first release:**

| page | metric | notes |
|---|---|---|
| org | **Avg prompt tokens per call + trend** | The primary cost lever. Available from data the sync already carries. |
| org | **Spend by agent over time** | Not just totals — catches an agent whose behaviour changed after a prompt edit. |
| org | **Cost per call, and its distribution** | The top 10% of requests carry **32%** of all spend; the largest single prompt observed was 261,974 tokens. |
| platform | **Orgs ranked by spend** | With period-over-period change: the "who suddenly got expensive" view. |
| platform | **Burn rate and runway** | Spend/day against remaining OpenRouter credits. `agentbarn_openrouter_credits_remaining` and the `CreditsLow` alert already exist in `helm/monitoring/values.yaml`. |
| platform | **Unattributed bucket** | Shown honestly rather than silently dropped — 18 rows today, plus any future orphans. |
| platform | **Model mix across the platform** | 21 distinct models in use; informs allowlist decisions. |

All seven are computable from the per-request rows the sync job already stores. None require new plumbing.

**Possible future additions** (not in scope):

| metric | why deferred |
|---|---|
| Cost per conversation | **Not available today.** `session_id` is populated on 100% of rows but is unique per request — 11,627 sessions for 11,627 calls, max 1 call each. It is a request id, not a conversation id. Would require the API to stamp its own conversation id into LiteLLM metadata at request time: a small change with a high payoff. Relates to the deferred per-user/per-conversation attribution decision. |
| Cost per skill / tool | `mcp_namespaced_tool_name` exists on the row but is empty across all 40,769 production rows. |
| Time-to-first-token, and cost/latency tradeoff by model | `completionStartTime` is 100% populated, so this is available whenever wanted. |
| Model comparison at equal work ($/1K calls) | Computable from existing rows; deferred as a refinement of the model mix view. |
| Idle-but-costly agent detection | Agents still accruing spend while unused. |
| Failed-request cost and count | 1,880 failures are invisible today — see defect #6, already a recommendation. |
| Healed-row count per period | Would have made this investigation unnecessary. Related to the deferred alerting decision. |
| ~~Runtime split (OpenClaw vs Hermes)~~ | **Investigated and rejected.** `request_tags` carries the client library, not the runtime. It fails on two counts: 22 of 101 agents emit *both* Python and JS tags, so it is not a per-agent property; and the split is chronological — JS ran 2026-05-17 to 2026-07-24 and stopped, Python began 2026-06-01 and continues — which reads as an SDK migration, not a runtime distinction. All 26 running agent pods are Hermes while Python is 93% of rows, so the mix is inconsistent with a runtime signal. Do not re-investigate. |
| Cache-hit ratio per org | Only available at daily resolution; see defect #3. |

**Note on precedent.** AF-247 is a template for the *platform* page only: event deliveries has no organization-scoped equivalent, so there is no existing example in the codebase of one surface rendered at two scopes. How the org and platform pages share components, schemas and hooks while differing in scope resolution and RBAC is an implementation-stage design decision, not settled here.

### Correction to offer the team lead

> "i remember we bumped litellm to add the newer models as they were not being tracked (same issue will happen in the future)"

Accurate for the era he remembers, but the rule has changed. Pre-upgrade, a model outside the catalog recorded $0 — exactly as described. Post-upgrade, cost comes from OpenRouter's per-request figure and the catalog is ignored entirely, so **a new model can no longer break tracking**; see [The catalog no longer determines cost tracking](#the-catalog-no-longer-determines-cost-tracking). What can still break it is a LiteLLM regression or a truncated stream — which is what the healing job should watch for.

## Recommendations

Ordered by value, not effort.

Re-ordered to match the team lead's decisions of 2026-09-02.

| # | Action | Rationale |
|---|---|---|
| 1 | **Persist cost in a table we own**, synced by a scheduled job modelled on the existing event reconciler. | Hard prerequisite for everything below: the requested platform UI needs server-side filtering and pagination, which LiteLLM's non-paginated endpoint cannot support. Also the only place healed and backfilled figures can live. |
| 2 | **Build the healing job**: scan `/spend/logs/v2` for `status='success' AND total_tokens > 0 AND spend = 0 AND request_id` starting `gen-`, then heal from OpenRouter, writing cost **and** token counts. | Kalkidan's "data healing". One mechanism covers the ongoing truncated-stream leak, the historical backfill, and insurance against a future LiteLLM regression. |
| 3 | **Backfill the lost window** through that job, tagged `openrouter_backfill`. | **A live client (GG Media Group) is on this data.** Recovers ~$322 of real per-agent spend — exact retrieval, not estimation. Runs unattended on the job's first tick (~22 min at 16-way for the largest deployment); the app is client-deployed, so nothing can be fired by hand. |
| 4 | **Build `/platform/costs`** modelled on AF-247: stat cards, server-side filters/search, infinite-scroll table, per-org breakdown, existing charts retained. | The requested deliverable. Reuses `require_platform_admin()` and `PaginatedItems[T]`; no new RBAC concept. |
| 5 | **Make a failed cost query visible.** Stop returning `{}` from `get_global_spend_report()`; surface an explicit error state. | The reason this went unseen for three months. Prevents recurrence of *any* future defect here. |
| 6 | ~~Split the OpenRouter key per environment.~~ **Declined.** | Each environment tracks its own traffic instead. Account-level reconciliation is consequently unavailable; local dev keeps spending production credit. |
| 7 | ~~Reconcile against OpenRouter.~~ **Dropped.** | The aggregate check is unprovable with a shared key; per-request sampled verification is deferred as a low-cost future addition. The zero-cost-row alert (#5 area) remains the only automated detector. |
| 8 | **Pin LiteLLM explicitly and equally** across `helm/litellm/values.yaml` and `compose.yml`; treat the version as cost-critical. | AF-233 fixed production but left `compose.yml` behind, so local dev kept reproducing the bug (§7). |
| 9 | ~~Set `max_budget` / `budget_duration` and `tpm`/`rpm` on generated keys.~~ **Deferred — known gap.** | Credit exhaustion is explicitly out of scope this round; a runaway agent remains bounded only by the OpenRouter key limit. |
| 10 | Surface `failed_requests` in the cost models and UI. | Data already collected and discarded; 1,880 failures are invisible today. |
| 11 | Reconcile `get_agent_cost()` and `get_org_cost_summary()` onto one date-ranged source. | Removes a class of "the numbers don't match" reports. |
| 12 | **Preserve all cost history across agent deletion** — denormalized ids, no cascade, captured display name. | Team lead decision: all history survives. Recovers the 3.3% orphan share and is a hard requirement of the platform view. |

**Not recommended:** maintaining a local model price map, or tracking infrastructure cost. The catalog is not consulted at all post-upgrade (proven above) and 290 paid OpenRouter models are missing from it; provider-reported cost is the correct source, and the work is in verifying it, not replacing it. Infrastructure cost is explicitly out of scope per the team lead.

### Backfill is possible, and exact

An earlier draft of this document stated the lost spend was unrecoverable. **That was wrong.**

`LiteLLM_SpendLogs.request_id` is OpenRouter's own generation ID (`gen-1786984666-SwLOzuELb22lpjGZiKs2`). All 19,135 affected production rows carry one, and `GET /api/v1/generation?id=` still returns the true cost for them. Verified on a random 25-row sample spanning the whole window:

```
resolved  : 25/25   (100% hit rate — no expiry observed back to May)
recovered : $0.4206  (avg $0.01682 per generation)
latency   : avg 1.35s, max 2.71s
```

Extrapolated over 19,135 rows that is **~$322**, which independently corroborates the ~$313.54 derived from rate arithmetic — two unrelated methods agreeing within 3%.

It is also **attributable**: `/spend/logs/v2` carries `agent_id` and `organization_id` on each row (verified against production by joining `api_key` to `LiteLLM_VerificationToken.metadata->>'agent_id'`, which returns the same identity). This is retrieval of real per-request figures, not estimation.

**Do not write the recovered values into LiteLLM's tables.** Three reasons:

1. **It would not work.** Spend lives in `LiteLLM_SpendLogs`, `LiteLLM_DailyUserSpend`, and `LiteLLM_VerificationToken.spend`. The Costs page reads the aggregated endpoint, which is built from `DailyUserSpend` — patching request rows changes nothing in the UI. Making it move means hand-editing three tables of a vendor schema that Prisma migrates on every upgrade.
2. **It destroys the audit trail.** Overwriting the zeros makes "recorded live" and "reconstructed later" indistinguishable — the exact distinction this incident shows we need.
3. **It is an irreversible production write** on already-damaged data.

Land it in a table we own instead (see below), tagged by source.

**Effort:** 20,412 generation lookups (19,135 prod + 1,277 staging). See [Rate limits and sizing](#rate-limits-and-sizing) for the measured latency, page counts and concurrency guidance — OpenRouter publishes no paid-tier rate limit, so backoff must be adaptive rather than tuned to a fixed rate.

### Persisting cost in a table we own

The Costs domain currently persists nothing; it queries LiteLLM at read time. That is why a LiteLLM outage renders as $0.00, and why there is nowhere to put backfilled figures. A table we own fixes both.

**Hook — pull, on a schedule.** The repository already has this pattern: [`api/domains/events/reconciliation.py`](api/domains/events/reconciliation.py) with [`event-delivery-reconciliation-cronjob.yaml`](helm/agentbarn-api/templates/event-delivery-reconciliation-cronjob.yaml), including batching, a thread pool, and a max-runtime guard. The cost job is the same shape, paginating `/spend/logs/v2` since a watermark and upserting per-request rows. Healing is phase 2 of that same job — see below.

- No LiteLLM configuration change, no new ingress, no new failure mode.
- Idempotent — re-running a window overwrites identical rows, so a missed run self-heals.
- Cheap — ~700 rows/day in production; 39,833 lifetime.
- It is also where a healed-row counter would live if alerting is added later (see "Alerting: out of scope").

**Cache tokens are deliberately out of scope.** They exist only in the daily rollup, never per request, so nothing in this job carries them. See defect #3 for what that gap costs us and what the minimal version would be if it is ever revisited.

**Alternative — push, per request.** LiteLLM's `callbacks:` list (currently `["prometheus"]`) also accepts a webhook or custom callback firing per completion, carrying `response_cost`, token counts, and `user_api_key_metadata` — which already holds `agent_id` and `organization_id` because `generate_key()` writes them. Real-time and per-request, but fire-and-forget: events are lost if our endpoint is slow or down, and agent latency must never depend on our cost writer. **Push still requires pull as a backstop**, so build pull first.

**Schema and sync decisions (settled):**

- **Unique on `request_id`** so upserts are idempotent and healing can target a single row.
- **Spend column `NUMERIC(20, 12)`.** Cast LiteLLM's float straight in, **no rounding at ingest**; round only for display. Token counts stay `INTEGER` (LiteLLM's own type, already exact).
- **Denormalize `agent_id`, `organization_id` and their display names** at write time, so deleting an agent cannot orphan history and the UI can render "agent_name in org_name" for agents that no longer exist. Fixes defect #4 as a side effect.
- **A `source` column** (`litellm_live` vs `openrouter_backfill`) so recovered figures sit alongside live ones without ever blurring measured and reconstructed data. It is also what makes healing self-resuming — the trigger query excludes rows already tagged as healed.
- **Watermark overlap: 60 minutes.** Query `startTime > watermark - 60 min`, not `> watermark`. Advance the watermark to `max(startTime)` of ingested rows, never to "now".

### Why 60 minutes, and why `NUMERIC`

**Overlap.** `startTime` is when a request *began*, but LiteLLM writes spend logs asynchronously after completion, so a row can surface long after its own timestamp — and there is **no insertion-order column** (`startTime`, `endTime`, `completionStartTime` are all request-clock; no `created_at` exists, and `/spend/logs/v2` defaults `sort_by` to `startTime`). A strict `> watermark` would skip late arrivals **permanently and silently**.

Measured on production successes:

| | |
|---|---|
| max request duration | **1,230.9 s (20.5 min)** |
| p99.9 | 279.2 s |
| p99 | 98.0 s |

60 minutes covers the observed maximum roughly threefold. The cost is negligible — at ~700 rows/day that re-reads about 30 rows per run, and re-reading is a no-op because upserts are keyed on `request_id`.

The skew matters more than the volume: the rows most likely to arrive late are the longest-running ones, which are also the most expensive and the most likely to have been truncated. A naive watermark would systematically drop exactly the requests the ledger is weakest on.

**`NUMERIC` over float.** Note this is *not* for drift: summing all 40,674 production rows as `float8` versus `numeric` differs by **7.96e-13** — negligible at our magnitudes. The reasons are:

- **Exact equality.** Healing compares recorded values against OpenRouter's. With floats that means epsilon comparisons and a chosen tolerance; with `NUMERIC` it is plain equality.
- **Deterministic aggregates.** Float addition is not associative, so Postgres can return slightly different sums for the same query depending on plan or parallelism — an org total and its constituent rows could disagree between renders.
- **It is client-billing data.** GG Media Group's invoiced figures come out of this table.

12 decimal places sits comfortably below the smallest real value: cheap models run to $4x10^-8 per token, and OpenRouter reports costs such as `0.00000498`. **Never round to 2 or 4 decimals anywhere in the pipeline** — a legitimate sub-cent request rendered as `$0.00` is indistinguishable from the defect this whole document is about.

---

### The healing job: what still writes $0

With the catalog out of the picture, only one live scenario still records zero cost for a real charge — and it is reproducible on demand.

**Client disconnects mid-stream.** Killing the client 3 s into a long generation:

| | LiteLLM recorded | OpenRouter truth | under-recorded |
|---|---|---|---|
| **aborted** stream | pt=21, ct=**0**, **$0.00000000** | finish=`length`, ct=**1200**, **$0.00265820** | **$0.00265820** |
| control, allowed to finish | pt=26, ct=1200, $0.00265820 | ct=1200, $0.00265820 | $0 |

The generation **ran to completion server-side and was charged in full** — OpenRouter reports `finish_reason: length` and 1,200 completion tokens. The client simply was not there to receive the trailing usage chunk, so LiteLLM logged `completion_tokens = 0` and `spend = 0` while the money was spent. This is precisely the production signature from [Current state](#current-state): 19 rows, `status='success'`, 42% with `completion_tokens = 0`, averaging 57.6 s against 10.8 s for priced rows.

**One job, two phases.** Sync and healing are not separate jobs — they are ordered phases of a single scheduled run, modelled on the existing event reconciler:

```
phase 1  SYNC   /spend/logs/v2 (paginated, page_size<=1000, since watermark)
                -> upsert per-request rows into our table

phase 2  HEAL   SELECT ... FROM our_table
                 WHERE status = 'success'
                   AND total_tokens > 0
                   AND spend = 0
                   AND request_id LIKE 'gen-%'
                   AND source <> 'openrouter_backfill'
                -> GET /api/v1/generation?id=
                -> UPDATE with true cost + token counts, source = 'openrouter_backfill'
```

**The trigger reads from our own table**, not from LiteLLM. Phase 1 has already landed the rows locally, so phase 2 never calls LiteLLM again — it reads our table and calls OpenRouter. LiteLLM is touched exactly once per row, at sync time.

This also gives premature-healing protection for free: a request still in flight, or one LiteLLM has not yet flushed to its spend log, simply is not in our table and cannot be picked up. Healing latency is therefore governed by phase 1's watermark logic, not by a separate rule.

**The backfill is not a third job, and is never fired manually.** It is the same query finding more rows on its first run — see [Why healing runs unbounded](#why-healing-runs-unbounded-with-no-first-run-special-case).

### Why the sync source is `/spend/logs/v2`

The trigger needs *per-request* rows carrying `request_id`, which rules out the alternatives:

| candidate sync source | per-request? | paginated | in the OpenAPI spec | usable |
|---|---|---|---|---|
| `GET /user/daily/activity/aggregated` | no — per day x key x model, no request IDs | no | yes | **no** |
| `GET /spend/logs` | no — `summarize` defaults to **true**, returning key-level aggregates | no | yes | **no** |
| `GET /spend/logs/ui` | yes | yes | **no — absent from the schema** | **no** |
| **`GET /spend/logs/v2`** | **yes** | **yes, `page_size` max 1000** | **yes** | **yes** |

`/spend/logs/ui` works but is an internal UI endpoint that does not appear in the proxy's own `/openapi.json`, so it can change without notice. `/spend/logs/v2` is the versioned, supported equivalent and is strictly more capable — it also exposes `min_spend`, `max_spend`, `status_filter`, `model`, `key_alias`, `error_code`, `sort_by` and `sort_order`.

An earlier draft proposed syncing from `/user/daily/activity/aggregated`. That was wrong on three counts: no `request_id` (cannot drive healing), per-day granularity (cannot back a row-level UI with search and filters — the deliverable Kalkidan asked for), and it is the non-paginated endpoint. `/spend/logs/v2` solves all three.

It returns `{data, total, page, page_size, total_pages, total_is_capped}` with per-row `request_id`, `spend`, `status`, `total_tokens`, `prompt_tokens`, `completion_tokens`, `model`, `cache_hit`, `request_duration_ms` — **and `agent_id` and `organization_id` directly on the row**, so no `api_key` -> `LiteLLM_VerificationToken` -> `metadata` join is needed for attribution.

Volume is not a concern: 39,833 requests lifetime in production, roughly 700/day.

**Granularity:** one row per completion call — not per user message. An agent turn involving tool calls produces several rows. Rows for failed requests carry a UUID rather than a `gen-` id and have no OpenRouter counterpart at all.

**Trigger verified** against the local ledger — three matches, zero false positives (the 403 row excluded by its UUID, priced rows by `spend > 0`):

```
gen-1788343064-B0OWtMSWsDJ69BWJz2Ko  tokens=21  spend=0.0  status=success   <- aborted stream
gen-1788265668-dCXZXmQMvVNvUOO7GzU2  tokens=35  spend=0.0  status=success   <- pre-fix repro
gen-1788265298-xOrCuTxeqDDvTwqSO7BK  tokens=35  spend=0.0  status=success   <- pre-fix repro
```

**OpenRouter traffic is negligible in steady state.** Phase 1 makes zero OpenRouter calls. Phase 2 calls it only for trigger matches — in production that is ~19 healable rows per two weeks against ~10,000 requests. The one-time backfill is the only bulk pass.

### Rate limits and sizing

**Documented — LiteLLM** (from the pinned v1.96.2 build's own `/openapi.json`, so authoritative for what we run):

| parameter | value |
|---|---|
| `/spend/logs/v2` `page_size` | default **50**, **maximum 1000**, minimum 1 |
| `/spend/logs/v2` `page` | minimum 1, default 1 |
| server-side filters | `min_spend`, `max_spend`, `status_filter`, `model`, `model_group`, `key_alias`, `end_user`, `error_code` |
| ordering | `sort_by` (default `startTime`), `sort_order` (default `desc`) |
| response meta | `total`, `page`, `page_size`, `total_pages`, `total_is_capped` |

**Documented — OpenRouter:**

| | value |
|---|---|
| free models (`:free`) | 20 requests/minute |
| free daily, < 10 credits purchased | 50 requests/day |
| free daily, >= 10 credits purchased | 1,000 requests/day |
| **paid models and metadata endpoints** | **no published RPS or RPM cap** — only "DDoS protection" |
| 429 response | carries `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` |

**The paid-tier limit is undocumented — but was not reachable in practice.** Benchmarked against production generation IDs, 260 requests at rising concurrency:

| concurrency | requests | req/s | 429s | errors | p50 latency |
|---|---|---|---|---|---|
| 1 | 20 | 0.84 | 0 | 0 | 1.12 s |
| 4 | 60 | 3.60 | 0 | 0 | 1.04 s |
| 8 | 60 | 7.06 | 0 | 0 | 1.01 s |
| 16 | 60 | **14.27** | 0 | 1 | 1.04 s |
| 32 | 60 | 17.95 | 0 | 0 | 1.02 s |

**Zero 429s at any level**, with latency flat at ~1 s throughout. OpenRouter's throttle was never reached; the plateau between 16 and 32 looks like client-side connection limits rather than server pushback. Keep 429 backoff regardless — our account's history is not necessarily representative of a client deployment's.

**These lookups cost nothing.** `/generation` is a metadata read of an existing record; it runs no inference. Verified by reading `total_usage` before and after the benchmark: `$2340.514941` both times, delta `$0.00000000` across 260 requests.

**Derived sizing:**

| quantity | value |
|---|---|
| sync backfill, production | 40,674 rows / 1000 = **41 pages**, no OpenRouter calls, minutes |
| sync backfill, staging | 1,953 rows = **2 pages** |
| steady-state sync | ~700 rows/day = **1 page/day** |
| OpenRouter healing calls, one-time backfill | **20,412** (19,135 prod + 1,277 staging) |
| OpenRouter healing calls, steady state | **~19 per two weeks** |
| heal backfill wall time @ 8-way | ~45 min |
| **heal backfill wall time @ 16-way** | **~22 min** |
| heal backfill wall time @ 32-way | ~18 min |

LiteLLM is not the constraint at 41 pages. OpenRouter is, and only for the first run.

### Why healing runs unbounded, with no first-run special case

**Constraint:** the application is deployed per client, and most deployments are not reachable by us — GG Media Group's among them. **Nothing can be fired manually.** Any backfill must complete unattended, in every deployment, with nobody watching.

The benchmark makes that straightforward. At 16-way concurrency the **largest deployment we can measure finishes in ~22 minutes**, which is an ordinary scheduled job rather than a campaign.

**No cursor or progress table is required.** Because healing writes `source = 'openrouter_backfill'`, the trigger query already excludes rows it has repaired. Commit per row (or in small batches) rather than in one transaction, and the query becomes **self-resuming**: a crash fifteen minutes in simply means the next scheduled run finds fewer rows. Idempotency and resumability fall out of the data model.

The implementation is therefore just: **the trigger query, a worker pool, per-row commits.** No chunk bookkeeping, no first-run mode, no manual step.

**Keep one guard: a maximum runtime**, stopping and resuming on the next tick. `api/domains/events/reconciliation.py` already uses this pattern (`EVENT_DELIVERY_RECONCILIATION_MAX_RUNTIME_SECONDS`), so it is one familiar constant. It is the only protection against a client deployment substantially larger than production — precisely the case we cannot inspect or intervene in.

**Settings:**

- **Concurrency 8-16**, not 32 — the gain above 16 is marginal and client keys carry their own unknown limits.
- **Process newest-first**, so recent costs become accurate first while older rows backfill behind them.
- **Retain 429 backoff** via `X-RateLimit-Reset` even though none was observed.

**Cutover is not blocked by any of this.** The sync backfill lands full history in minutes, with pre-Aug-17 costs still wrong — exactly as the current page shows them today. Cutover is therefore never worse than present behaviour, and healing corrects those figures progressively afterwards.

**Client-visible consequence:** historical costs *rise* as healing proceeds. Deployments will see corrected figures appear over the following minutes to hours. A UI signal while healing is incomplete is worth considering, and the commercial question — clients already invoiced on understated figures — now lands automatically on release rather than when someone chooses to run a script. See [Backfill is possible, and exact](#backfill-is-possible-and-exact).

**Incidental from `/generation`:** the response carries `native_tokens_cached` and `cache_discount` alongside `total_cost`. Cache tracking is out of scope (defect #3), so these are simply not read — but note that even if they were, they would only ever cover rows entering the healing path, not the 614M cache-read tokens on rows priced correctly all along.

**Three problems, one mechanism:**

1. **Truncated streams** — the ongoing leak. Not a rounding error: the aborted request above under-recorded by 100% of its cost, and it is the long, expensive generations that get cut off, so the money-weighted impact exceeds the row-count share.
2. **The historical backfill** — the same query on its first run, finding 19,135 rows instead of a handful, recovering the ~$322 from the pre-fix era. No separate code path and no manual trigger.
3. **Regression insurance** — if a future LiteLLM breaks passthrough again, damage is repaired automatically instead of going unnoticed for three months.

**What it must never touch: failed requests.** A 403 from `ibm-granite/granite-4.2-8b` produced a spend row whose `request_id` is a **UUID, not a `gen-` id** — no OpenRouter generation exists and nothing was charged. The `gen-` prefix test is what separates "we lost the cost" from "there was no cost", and it is why 455 of the 474 zero rows are correctly left alone.

**Four spec notes:**

- **Date format is `YYYY-MM-DD HH:MM:SS`**, not a plain date — a bare `2026-09-01` returns HTTP 400 (`Invalid date format`). Sibling endpoints accept plain dates, so this inconsistency will catch someone; pin it in the implementation.
- **The trigger can be pushed server-side** for the two cases that do not need a full sync: `?max_spend=0&status_filter=success&page_size=1000` returns only the candidate rows. Verified — 3 rows, `total_pages=1`, zero false positives. Useful as a cheap standalone detector should alerting be added later; the steady-state loop still syncs everything because the platform UI needs the full table.
- **It is paginated**, so walking the ~19,135 historical rows is a normal page loop rather than one huge query. Honour `total_is_capped`, which flags a truncated count.
- **Do not heal immediately.** Allow a lag before the first attempt and treat a 404 as retryable rather than terminal.
- **Token counts are wrong too, not just cost.** The aborted row recorded `ct=0` where OpenRouter counted 1,200. Write back tokens alongside spend, or every token-based metric stays understated even after the money is corrected.

---

## Scope decisions (round 2)

| Question | Decision | Consequence |
|---|---|---|
| Split the OpenRouter key per environment? | **No.** Each environment tracks its own traffic; prod's ledger covers prod alone, staging's covers staging. | Account-level reconciliation against OpenRouter is unprovable and is dropped — see below. Local development continues to spend production credit. |
| Accuracy or credit exhaustion? | **Accuracy.** Credit exhaustion accepted as a **known gap**. | No per-agent budget caps for now; a runaway agent is bounded only by the OpenRouter key's own limit. |
| Per-user / per-conversation attribution? | **Per-agent is sufficient.** | Recorded as a **possible future feature**; the per-request table does not preclude it, since rows carry `session_id` and `end_user`. |
| How much cost history survives agent deletion? | **All of it.** | Cost rows must never cascade from agent deletion, and the platform view must render spend for agents that no longer exist. |

### Verification against OpenRouter: dropped

Reconciling our recorded spend against OpenRouter's **account total** was the check that would have caught the original defect in days rather than months. With one key shared across production, staging and local development, that total is the sum of all three and cannot be decomposed. **The aggregate check is mathematically unprovable and is dropped.**

Two clarifications worth keeping on record, because they are easy to conflate:

- **Key sharing has not corrupted any data.** Each environment's LiteLLM database records only its own traffic. The bad data came from the streaming defect, nothing else. Key sharing costs exactly one capability — the account-level comparison — and leaves the rows themselves untouched.
- **Per-request verification is not blocked by key sharing.** A generation ID belongs to exactly one request in exactly one environment, so "does our recorded cost for `gen-...` match OpenRouter's?" is answerable regardless of how many environments share a key. Only the aggregate question is unanswerable.

**Decision: drop verification against OpenRouter entirely for this round** and focus on patching the identified gaps. Per-request sampled verification remains available at low cost if it is ever wanted — the healing job already makes exactly that call for zero-cost rows, so extending it to sample priced rows is a small delta rather than new machinery.

**Accepted risk:** with reconciliation dropped and no alerting planned (see below), there is no automated detector of a future regression at all. Healing would repair missing cost silently; a defect recording a *wrong non-zero* value would not be detected by anything.

### Alerting: out of scope, noted as a future addition

**No alerting is planned this round.** Recording it explicitly, because the gap arose from re-prioritisation rather than a decision, and because it leaves the design with **no automated detector of any kind**: reconciliation is dropped, budget caps are deferred, and healing repairs rows silently.

**Healing masks the signal it repairs.** If a future LiteLLM upgrade breaks cost passthrough again, the healing job would quietly repair every affected row — issuing on the order of 10,000 OpenRouter lookups a day — and the Costs page would look entirely healthy. A silent data loss becomes a silent, expensive, self-repairing workaround. Nobody would notice until someone questioned the job's runtime or the API traffic.

**If added later, alert on the healing *rate*, not on the existence of zero-cost rows.** A handful of healed rows a week is normal stream truncation. Hundreds a day means upstream capture is broken:

- emit a counter of healed rows from phase 2 of the cost job;
- alert when it exceeds a normal-truncation baseline (production currently runs ~19 per two weeks).

**The plumbing already exists.** `helm/monitoring/values.yaml` carries 13 Prometheus rules — `LiteLLMDown`, `OpenRouterCreditsLow`, `OpenRouterCreditsUnknown`, `AgentsInErrorState`, `HighToolCallErrorRate` among them — and `api/core/metrics.py` already defines the registries. Adding one counter and one rule is a small change alongside them.

### What the deletion decision requires

Cost history already outlives agents in production: spend logs begin 2026-05-17 while the oldest surviving agent was created 2026-05-19, and 59 of 84 spending keys reference agents that no longer exist. Preserving all history therefore means:

- Denormalize `agent_id` **and** `organization_id` onto every cost row at write time; never join to `agent` at read time.
- No foreign key from cost rows to `agent`, and no cascade on delete.
- Capture the agent's display name at write time, or the platform view will render deleted agents as bare UUIDs.
- This resolves defect #4 outright — the 3.3% orphaned share stops being orphaned.

---

## Appendix: reproducing this

Local k3d environment, per `README.md` → "Local Kubernetes (k3d) dev environment":

```bash
./run.sh
```

Mint a key, then send the same request twice — once with `"stream": false`, once with `"stream": true` — to `http://localhost:7070/v1/chat/completions` using `openrouter/z-ai/glm-5.2`. Then read the ledger:

```bash
docker exec aai_litellm_db psql -U litellm -d litellm -c "select model, count(*) reqs, sum(prompt_tokens+completion_tokens) tokens, round(sum(spend)::numeric,6) spend from \"LiteLLM_SpendLogs\" group by 1 order by tokens desc;"
```

On `main-v1.83.14-stable.patch.3` the streamed request records tokens and $0.00. On `v1.96.2` both record the same non-zero cost.

**Note:** the local `.env` currently uses the production OpenRouter key (§8), so this experiment spends production credit until the keys are split.

### Verification queries used (production, read-only)

Era split:

```sql
select case when "startTime" < '2026-08-17 19:31' then 'pre' else 'post' end as era,
       count(*), sum(total_tokens), round(sum(spend)::numeric,4),
       round((sum(spend)/nullif(sum(total_tokens),0)*1000000)::numeric,4) as usd_per_mtok
from "LiteLLM_SpendLogs" group by 1;
```

The zero-cost-success detector, kept for reference should alerting be added later:

```sql
select count(*) from "LiteLLM_SpendLogs"
where status = 'success' and total_tokens > 0 and spend = 0
  and "startTime" > now() - interval '1 day';
```

All production access for this investigation was read-only.
