"""Recorded LLM responses for deterministic evals (TESTING_STRATEGY §5).

A recording maps a hash of the prompt to the text the model returned. Fence tokens are
random per call, so they are normalised before hashing; everything else in the prompt is
deterministic for a given case (fixed run IDs, deterministic evidence). A changed prompt
means a missing recording and a failed case, never a silent pass.
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


class ReplayClient:
    """Serves recorded responses in order per prompt; never touches the network."""

    def __init__(self, recording: Recording, provider: str = "openrouter") -> None:
        self.provider = provider
        self.model = recording.model
        self._queues = {k: list(v) for k, v in recording.entries.items()}

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        queue = self._queues.get(prompt_hash(messages))
        if not queue:
            raise RecordingMissingError("no recorded response for this prompt")
        entry = queue.pop(0)
        return RawCompletion(
            text=entry["text"],
            model=entry.get("served_model") or self.model,
            served_by=entry.get("served_by"),
            input_tokens=entry.get("input_tokens"),
            output_tokens=entry.get("output_tokens"),
        )
