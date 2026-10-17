"""One-request structured-output probe for a free model (ADR-0026).

    uv run python -m querycure.llm.probe [--model MODEL]

Sends exactly one small request (no repair, no retry, no fallback) through the same client and
validation path an agent uses, and prints whether the answer validated, the served model,
latency and the error class. It uses one request of the daily free allowance and writes
nothing anywhere. Never part of startup or tests.
"""

import argparse
import asyncio
import json
import sys
import time
from typing import Literal

from pydantic import BaseModel, Field

from querycure.core.config import Settings
from querycure.llm.credentials import resolve_api_key
from querycure.llm.models import model_warning
from querycure.llm.providers import build_client
from querycure.llm.structured import LLMError, RetryPolicy, call_structured
from querycure.llm.types import CallRecord, ChatMessage


class ProbeAnswer(BaseModel):
    """Shaped like a hypothesis: enum, nested list and a bounded string."""

    category: Literal["missing_index", "inefficient_sort", "other"]
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    summary: str = Field(min_length=1, max_length=200)


PROMPT = [
    ChatMessage(
        role="system",
        content="You classify a PostgreSQL plan problem. Cite the evidence IDs you rely on.",
    ),
    ChatMessage(
        role="user",
        content=(
            "[ev_000000000001] (plan_node) Seq Scan on orders; filter customer_id = $1; "
            "100,000 rows\n[ev_000000000002] (plan_node) Sort by created_at DESC"
        ),
    ),
]


async def probe(settings: Settings, model: str) -> dict[str, object]:
    if settings.llm_provider == "stub":
        return {"model": model, "status": "skipped", "reason": "LLM_PROVIDER=stub"}
    key = resolve_api_key(settings, settings.llm_provider)
    client = build_client(settings.llm_provider, model, key, settings=settings)
    records: list[CallRecord] = []

    async def keep(record: CallRecord) -> None:
        records.append(record)

    started = time.monotonic()
    result: dict[str, object] = {"model": model, "warning": model_warning(model)}
    try:
        answer = await call_structured(
            client,
            PROMPT,
            ProbeAnswer,
            policy=RetryPolicy(
                max_retries=0,
                max_timeout_retries=0,
                repair_attempts=0,
                call_timeout_seconds=settings.llm_call_timeout_seconds,
            ),
            after_call=keep,
        )
        result |= {"status": "valid", "served_model": answer.model}
    except LLMError as exc:
        result |= {"status": "failed", "error_code": exc.code, "cause": exc.cause}
    result |= {
        "latency_ms": int((time.monotonic() - started) * 1000),
        "requests": len(records),
        "served_by": records[-1].served_by if records else None,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", help="model id (default: LLM_MODEL)")
    args = parser.parse_args(argv)
    settings = Settings()
    outcome = asyncio.run(probe(settings, args.model or settings.llm_model))
    print(json.dumps(outcome, indent=2))
    return 0 if outcome.get("status") == "valid" else 1


if __name__ == "__main__":
    sys.exit(main())
