# ADR-0027: Groq as a local-profile provider, trusted to be on its free plan

- Status: Accepted (2026-10-17, owner decision); amends ADR-0016
- Area: LLM / Configuration

## Context

The owner wants to run investigations on Groq with a server key in `backend/.env`. ADR-0016 allows only free OpenRouter models while `LLM_FREE_ONLY` is on, and it enforces this in code: model ids must be free (`:free` or `openrouter/free`), and every response must report a cost of exactly 0.

Groq doesn't fit those checks:
- its model ids say nothing about price;
- its responses carry no cost field.

So QueryCure can't verify that a Groq call was free. Whether one is free depends on the account's plan. On the free plan nothing is billed (it has rate limits instead); a key on a paid plan is billed.

Two options were offered to the owner:
1. Allow Groq only with `LLM_FREE_ONLY=false`, which keeps ADR-0016 exact.
2. Allow Groq with `LLM_FREE_ONLY` on, trusting that the key is on the free plan.

The owner chose option 2, for the server `.env` only, with no bring-your-own-key (BYOK) support.

## Decision

1. Add `LLM_PROVIDER=groq` with `GROQ_API_KEY` and `GROQ_BASE_URL` (default `https://api.groq.com/openai/v1`). `llm/groq.py` calls Groq's OpenAI-compatible API directly with JSON mode, `temperature=0` and no SDK retries (`llm.structured` owns retries).
2. While `LLM_FREE_ONLY` is on, the config guard accepts `groq` and any Groq model id, for `LLM_MODEL` and `LLM_FALLBACK_MODEL`. The fallback uses the same provider and key.
3. Errors go through the same classifier as OpenRouter:
   - a per-day 429 → `FreeQuotaExhaustedError`, so the run stops and never falls through to anything paid;
   - a per-minute 429 → a retryable rate limit;
   - 401/403 → an authentication failure.
4. `LLM_REQUESTS_PER_MINUTE` gates Groq calls. The `LLM_DAILY_REQUEST_LIMIT` count doesn't apply: it counts OpenRouter free model ids, and Groq enforces its own daily limit.
5. Local profile only. `GROQ_API_KEY` is refused at startup in the demo profile, like `OPENROUTER_API_KEY` (a shared key would be spent by anonymous visitors). Groq isn't a BYOK provider, so the Settings page is unchanged.

## Consequences

- **Weaker guarantee.** With Groq, "free only" is a promise the operator makes, not a check QueryCure performs. `.env.example` says so next to `GROQ_API_KEY`. ADR-0016's guarantees for OpenRouter are unchanged.
- **Unknown reliability.** No Groq model has recorded structured-output evidence, so the worker logs `llm_model_untested` at startup. Check a model with `python -m querycure.llm.probe --model <id>` before relying on it.
- **Invalid JSON is not retried.** Groq's JSON mode returns HTTP 400 (`json_validate_failed`) when the model emits invalid JSON. That is classified as a rejected request, which is not retryable. The bounded fallback model still applies.
- **Evals unchanged.** Evals still record and replay against OpenRouter.
