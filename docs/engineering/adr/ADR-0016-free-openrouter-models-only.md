# ADR-0016: Free OpenRouter models only, enforced in code

- Status: Accepted (2026-10-12); amends the provider plan in ROADMAP Phase 2 ("Gemini + OpenRouter via LangChain") and open decision D3
- Area: LLM / Cost / Security

## Context
The project owner requires zero paid LLM usage in Phase 2 and every later phase: free OpenRouter models only, never a silent fallback to a paid model, and a graceful stop when free capacity runs out. Free models are less reliable than paid ones and the free tier is rate-limited. On the owner's key (`is_free_tier: true`) that means about 20 requests/minute and 50 requests/day.

Two facts found while implementing this shaped the decision:
- `openrouter/auto` and `openrouter/auto-beta` are listed at $0 in the model catalogue but route to paid models. A "price is zero" check alone would let paid usage through.
- `openrouter/free` is a router: a probe request was served by `nvidia/nemotron-3-super-120b-a12b:free` via provider `Nvidia`. The model that answers can change per request, so the served model must be recorded per call and a specific `:free` model should be pinned for reproducible evals.

## Decision
1. **Configuration guard** (`core/config.py`). With `LLM_FREE_ONLY=true` (the default), `LLM_PROVIDER` must be `openrouter`, and `LLM_MODEL`/`LLM_FALLBACK_MODEL` must be `openrouter/free` or an ID ending in `:free`. Anything else fails at startup. Paid models need an explicit operator opt-out (`LLM_FREE_ONLY=false`).
2. **Per-response cost check** (`llm/openrouter.py`). OpenRouter is called through its OpenAI-compatible API with the `openai` SDK, requesting `usage.include`. In free-only mode every response must report `usage.cost == 0`; a non-zero or missing cost raises `PaidUsageError`. LangChain's wrapper drops `cost`, `provider` and the served `model`, so it is no longer used for OpenRouter; Gemini via LangChain remains for operators who opt out.
3. **No paid fallback, ever.** Quota exhaustion (a per-day 429 or 402) and paid-usage detection are non-retryable and never go to the fallback client. The agent runner turns them into `BudgetExhausted`, so the run stops at the next node and `write_report` produces an `inconclusive` partial report.
4. **Free-tier limits** (`llm/rate_limit.py`):
   - a per-process sliding window (`LLM_REQUESTS_PER_MINUTE`, default 16 < 20);
   - a daily quota counted from `agent_executions` (one row per provider call), shared by all runs and surviving restarts (`LLM_DAILY_REQUEST_LIMIT`, default 45 < 50, leaving headroom for in-flight calls);
   - per-run LLM concurrency `LLM_MAX_CONCURRENCY` (default 1).
   Run budgets (calls, tokens) and bounded retries are unchanged.
5. **Provenance.** Every `agent_executions` row records the requested model, the model that answered (`model`) and the upstream provider (`served_by`). Migration `0007`.
6. `require_parameters: true` asks OpenRouter to route only to endpoints that support `response_format`.
7. Automated tests never call a provider: scripted clients, an HTTP mock transport for the OpenRouter client, and recorded responses for evals.

## Consequences
- Zero spend by construction, and a stop instead of a surprise bill if the catalogue or routing changes.
- Fewer runs per day (≈ 6–8 investigations at 5–8 calls each): eval recording and model benchmarking have to be frugal and may span days.
- Free models may produce worse JSON and reasoning. Repair, citation retry and deterministic guard rails absorb some of that; eval scores make the rest visible rather than assumed away.
- The pinned model is chosen by benchmark (Phase 2 eval results) and can be changed with `LLM_MODEL` or, later, BYOK settings.
