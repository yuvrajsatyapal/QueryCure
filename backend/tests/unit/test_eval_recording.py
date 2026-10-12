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
