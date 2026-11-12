# Decisions

## Read when

Read before asking a decision model anything from a platform feature, changing which models answer, or changing how answers are checked or billed.

## Role in the system

A **Decision** is one call that asks a decision model a fixed set of typed questions about a piece of state and gets calibrated answers back, instead of free text. Platform features use it to classify or score something an Agent produced; anomaly detection (MDP-44) is the first. The module knows nothing about its callers.

- `api/infrastructure/litellm/decisions.py` holds the question and answer types and the client. All provider wire format stays there, because OpenRouter's decisions route is alpha.
- `api/domains/decisions/` holds `DecisionService.decide`, which picks the model and the key, and the Platform setting.

## Asking

`DecisionService.decide(agent_id, state, questions, model=None)` asks every question in one call and returns answers keyed like the questions.

| Question | Answer |
| --- | --- |
| `YesNoQuestion(question, yes_means=None, no_means=None)` | `YesNoAnswer(probability)`: the probability of yes |
| `ChoiceQuestion(question, options={label: description})`, 2–255 options | `ChoiceAnswer(choice, confidence, probabilities)` keyed by label |
| `ScoreQuestion(question, levels=[lowest, …, highest])`, 2–10 distinct levels | `ScoreAnswer(score, level, confidence, probabilities)`: `score` is the probability-weighted level index from 0, `level` the nearest level, `probabilities` keyed by level |

The result also carries input and output tokens and `cost_usd` from LiteLLM (`None` when not reported). One call takes 1–128 questions. Questions outside these limits are a `ValueError` before any call.

**Pass derived features, not raw records.** `state` (text, or a JSON object or list) goes to the model provider as given. A caller that must keep rows, names or free text away from the provider reduces it first, e.g. to ratios, counts and z-scores.

## Models

- `DECISION_MODELS` maps a name to a LiteLLM model slug; the default is `{"jev": "openrouter/typesafe/jev-1.14", "openai": "openrouter/openai/gpt-6-luna-decisions"}`. A model version bump is a change to this map, not code.
- Platform Administrators choose the default name at `GET/PUT /api/v1/platform/settings/decisions`; `GET .../models` lists the configured names. Until they do, `DECISION_DEFAULT_MODEL` (default `jev`) applies, and the API refuses to start if it names no entry. A change and its Platform-scoped `platform.decision_model.changed` audit event commit together in `platform_decision_settings`; saving the current choice records nothing. Only configured names can be saved (`422` otherwise).
- A caller may pass `model=<name>` for one call; an unknown name is a `ValueError`. A saved choice later removed from `DECISION_MODELS` falls back to the default.
- Platform Settings → **Decisions** (`/dashboard/platform/settings?section=decisions`) holds the setting, in the model picker card shared with Agent Memory and Playbooks; `ui/src/features/decisions/` holds it.

## Calls, billing and failures

- Calls go to LiteLLM's System One route (`POST /v1/systemone`) and from there to OpenRouter on `OPENROUTER_API_KEY`, so they appear in spend logs and `cost_record` like any other model call. The route needs LiteLLM v1.104.3 or later.
- Every call is billed to the Agent's own LiteLLM key, as Playbook Extraction is, so it counts against the Agent's and its Organization's limits. A deleted Agent, or one without a usable key, is `key_or_model_rejected` without a call.
- Failures raise `DecisionError` with the same categories as chat completions: `budget_exceeded`, `key_or_model_rejected`, `unavailable`, `bad_response`. The error never carries request or response content.
- Answers are untrusted. Every question must be answered, with the matching answer type, a choice from the offered set, probabilities and confidences in [0, 1] and a score within the scale; an answer to a question not asked or anything else malformed fails the whole call as `bad_response`.

## Data retention

OpenRouter accepts `provider: {data_collection: "deny", zdr: true}` on its decisions route, but LiteLLM (v1.108.6) builds the upstream request from the model, state and questions only and drops it. Data collection and zero data retention are therefore set on the OpenRouter account, where they apply to every request on the key. With zero data retention enforced, OpenRouter serves `openai/gpt-6-luna-decisions` only through Azure.
