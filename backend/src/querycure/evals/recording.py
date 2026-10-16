"""Recorded LLM responses for deterministic evals (TESTING_STRATEGY §5).

A recording maps a hash of the prompt to the text the model returned. Fence tokens are
random per call, so they are normalised before hashing; everything else in the prompt is
deterministic for a given case (fixed run IDs, deterministic evidence). A changed prompt
means a missing recording and a failed case, never a silent pass.

One exception (Phase 4): prompts that embed *live sandbox measurements* (the Benchmark
Auditor's review, and Optimization Engineer rounds after the first, which list earlier
verdicts) differ on every run because the benchmark measures anew. For those agents only, a
missed exact match falls back to the next unused recorded answer of the same agent (matched by
the shape of its JSON output). The run's outcome is still decided by live measurements and the
deterministic rules, and every other prompt must still match exactly.
"""

import datetime as dt
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from querycure.llm.types import ChatClient, ChatMessage, RawCompletion

RECORDING_SCHEMA_VERSION = 1
_DATA = re.compile(r"<<DATA [0-9a-f]{16} kind=")
_END = re.compile(r"<<END [0-9a-f]{16}>>")


class RecordingMissingError(Exception):
    """No recorded response for this prompt: the prompt changed, so re-record the case."""


class LiveDivergenceError(RecordingMissingError):
    """A live-measurement prompt with no recorded answer left: this replay's sandbox
    measurements led the run down a different path than the recording (e.g. inconclusive
    here, verified when recorded). Not a prompt change and not a pass."""


def prompt_hash(messages: Sequence[ChatMessage]) -> str:
    normalised = [
        {"role": m.role, "content": _END.sub("<<END *>>", _DATA.sub("<<DATA * kind=", m.content))}
        for m in messages
    ]
    return hashlib.sha256(json.dumps(normalised, separators=(",", ":")).encode()).hexdigest()


def model_slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


@dataclass
class Recording:
    case_id: str
    model: str
    entries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    recorded_at: str | None = None

    @classmethod
    def load(cls, path: Path) -> "Recording":
        raw = json.loads(path.read_text())
        return cls(
            case_id=raw["case"],
            model=raw["model"],
            entries=raw["entries"],
            recorded_at=raw.get("recorded_at"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "schema_version": RECORDING_SCHEMA_VERSION,
            "case": self.case_id,
            "model": self.model,
            "recorded_at": self.recorded_at or dt.datetime.now(dt.UTC).date().isoformat(),
            "provenance": "recorded",
            "entries": dict(sorted(self.entries.items())),
        }
        path.write_text(json.dumps(body, indent=2, sort_keys=False) + "\n")


class RecordingClient:
    """Wraps a real client and keeps every successful response it returns."""

    def __init__(self, inner: ChatClient, recording: Recording) -> None:
        self.provider = inner.provider
        self.model = inner.model
        self._inner = inner
        self.recording = recording

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        completion = await self._inner.complete_json(messages)
        self.recording.entries.setdefault(prompt_hash(messages), []).append(
            {
                "text": completion.text,
                "served_model": completion.model,
                "served_by": completion.served_by,
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
            }
        )
        return completion


# (system-prompt marker, condition on the user content, keys the recorded answer must have)
_LIVE_PROMPTS: tuple[tuple[str, str | None, frozenset[str]], ...] = (
    ("You are the Benchmark Auditor", None, frozenset({"summary", "concerns"})),
    ("You are the Optimization Engineer", "Earlier rounds:", frozenset({"candidates", "summary"})),
)


def _keys(text: str) -> frozenset[str]:
    try:
        value = json.loads(text)
    except ValueError:
        return frozenset()
    return frozenset(value) if isinstance(value, dict) else frozenset()


class ReplayClient:
    """Serves recorded responses in order per prompt; never touches the network."""

    def __init__(
        self, recording: Recording, provider: str = "openrouter", *, exact_only: bool = False
    ) -> None:
        """`exact_only`: no same-agent fallback for live-measurement prompts. Used with
        prerecorded measurement fixtures, where those prompts are deterministic too, so any
        mismatch means the prompts changed (re-record), never a measurement divergence."""
        self.provider = provider
        self.model = recording.model
        self._queues = {k: list(v) for k, v in recording.entries.items()}
        self._exact_only = exact_only

    def _live_fallback(self, messages: Sequence[ChatMessage]) -> dict[str, Any] | None:
        if self._exact_only:
            return None
        system = messages[0].content if messages else ""
        user = "\n".join(m.content for m in messages[1:])
        for marker, needs, keys in _LIVE_PROMPTS:
            if marker not in system or (needs is not None and needs not in user):
                continue
            for key in sorted(self._queues):
                queue = self._queues[key]
                if queue and keys <= _keys(queue[0]["text"]):
                    return queue.pop(0)
        return None

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        queue = self._queues.get(prompt_hash(messages))
        entry = queue.pop(0) if queue else self._live_fallback(messages)
        if entry is None:
            system = messages[0].content if messages else ""
            if not self._exact_only and any(marker in system for marker, _, _ in _LIVE_PROMPTS):
                left = sorted(_keys(q[0]["text"]) for q in self._queues.values() if q)
                raise LiveDivergenceError(
                    f"live measurements took a path the recording lacks ({system[:40]!r}; "
                    f"{len(left)} unused recorded answer(s))"
                )
            raise RecordingMissingError("no recorded response for this prompt")
        return RawCompletion(
            text=entry["text"],
            model=entry.get("served_model") or self.model,
            served_by=entry.get("served_by"),
            input_tokens=entry.get("input_tokens"),
            output_tokens=entry.get("output_tokens"),
        )
