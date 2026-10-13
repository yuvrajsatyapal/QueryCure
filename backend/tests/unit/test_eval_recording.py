"""Eval recordings (T2.14): stable prompt hashes and strict replay."""

from pathlib import Path

import pytest

from querycure.agents.fencing import Fence
from querycure.evals.cases import load_cases
from querycure.evals.recording import (
    Recording,
    RecordingMissingError,
    ReplayClient,
    model_slug,
    prompt_hash,
)
from querycure.llm.types import ChatMessage


def _prompt() -> list[ChatMessage]:
    fence = Fence()
    return [
        ChatMessage(role="system", content="rules"),
        ChatMessage(role="user", content=fence.block("evidence", "[ev_0123456789ab] x")),
    ]


def test_fence_tokens_do_not_change_the_hash() -> None:
    assert prompt_hash(_prompt()) == prompt_hash(_prompt())


def test_any_other_change_does() -> None:
    changed = _prompt()
    changed[0] = ChatMessage(role="system", content="rules v2")

    assert prompt_hash(changed) != prompt_hash(_prompt())


async def test_replay_serves_in_order_then_refuses() -> None:
    key = prompt_hash(_prompt())
    client = ReplayClient(
        Recording(
            case_id="c",
            model="m:free",
            entries={key: [{"text": "one", "served_model": "x:free"}, {"text": "two"}]},
        )
    )

    first = await client.complete_json(_prompt())
    second = await client.complete_json(_prompt())

    assert (first.text, first.model, second.text) == ("one", "x:free", "two")
    with pytest.raises(RecordingMissingError):
        await client.complete_json(_prompt())


def test_recording_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    Recording(case_id="c", model="a/b:free", entries={"h": [{"text": "t"}]}).save(path)

    loaded = Recording.load(path)

    assert (loaded.case_id, loaded.model, loaded.entries) == (
        "c",
        "a/b:free",
        {"h": [{"text": "t"}]},
    )
    assert '"provenance": "recorded"' in path.read_text()


def test_model_slugs_are_file_safe() -> None:
    assert (
        model_slug("nvidia/nemotron-3-super-120b-a12b:free")
        == "nvidia_nemotron-3-super-120b-a12b_free"
    )


def test_shipped_cases_load() -> None:
    ids = {c.id for c in load_cases()}

    assert {
        "orders_missing_composite_index",
        "orders_injection_in_schema",
        "orders_plain_explain",
        "pk_lookup_already_optimal",
        "orders_budget_exhaustion",
    } <= ids


async def test_ledger_counts_requests_across_invocations(tmp_path: Path) -> None:
    from querycure.core.errors import BudgetExhaustedError
    from querycure.evals.runner import QuotaLedger, RequestCap

    ledger = QuotaLedger(tmp_path, "2026-10-12")
    first = RequestCap(2, ledger)
    await first.check()
    await first.check()
    with pytest.raises(BudgetExhaustedError):
        await first.check()

    second = RequestCap(5, QuotaLedger(tmp_path, "2026-10-12"))
    await second.check()

    assert QuotaLedger(tmp_path, "2026-10-12").used() == 3
    assert QuotaLedger(tmp_path, "2026-10-13").used() == 0


AUDIT = '{"summary": "s", "concerns": []}'
CANDIDATES = '{"candidates": [], "summary": "none"}'


def _agent(system: str, user: str) -> list[ChatMessage]:
    return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]


async def test_live_measurement_prompts_fall_back_to_the_same_agents_recorded_answer() -> None:
    """The auditor's prompt embeds this run's sandbox measurements, which change every run."""
    recorded = _agent("You are the Benchmark Auditor ...", "speedup 12.3x measured")
    client = ReplayClient(
        Recording(
            case_id="c",
            model="m:free",
            entries={
                prompt_hash(_prompt()): [{"text": "exact"}],
                prompt_hash(recorded): [{"text": AUDIT}],
            },
        )
    )

    live = await client.complete_json(_agent("You are the Benchmark Auditor ...", "speedup 11.9x"))

    assert live.text == AUDIT
    with pytest.raises(RecordingMissingError):  # used up: never served twice
        await client.complete_json(_agent("You are the Benchmark Auditor ...", "speedup 11.0x"))


async def test_fallback_never_crosses_agents_or_covers_deterministic_prompts() -> None:
    client = ReplayClient(
        Recording(case_id="c", model="m:free", entries={"h1": [{"text": CANDIDATES}]})
    )

    # An auditor prompt cannot take an Optimization Engineer answer.
    with pytest.raises(RecordingMissingError):
        await client.complete_json(_agent("You are the Benchmark Auditor ...", "x"))
    # A first-round Optimization Engineer prompt is deterministic: exact match only.
    with pytest.raises(RecordingMissingError):
        await client.complete_json(_agent("You are the Optimization Engineer ...", "Hypotheses: x"))
    # A later round embeds earlier live verdicts: the fallback applies.
    later = await client.complete_json(
        _agent("You are the Optimization Engineer ...", "Earlier rounds:\nverdicts")
    )
    assert later.text == CANDIDATES


async def test_exhausted_live_prompt_is_a_divergence_not_a_prompt_change() -> None:
    from querycure.evals.recording import LiveDivergenceError

    client = ReplayClient(Recording(case_id="c", model="m:free", entries={}))

    with pytest.raises(LiveDivergenceError):
        await client.complete_json(_agent("You are the Benchmark Auditor ...", "x"))
    with pytest.raises(RecordingMissingError) as other:
        await client.complete_json(_prompt())
    assert not isinstance(other.value, LiveDivergenceError)
