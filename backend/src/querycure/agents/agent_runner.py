"""One LLM agent invocation: structured call, citation check with one retry, persistence.

Idempotent per `invocation_key`: if a successful execution is already recorded (a node
re-run after a crash), its stored output is returned and no LLM call is made. Every
provider call becomes an `agent_executions` row (failed / invalid_output / succeeded); only
the accepted one is `succeeded` and points at the stored output artifact.
"""

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from querycure.agents.citations import CitationReport, feedback_message
from querycure.agents.runtime import RunContext
from querycure.core.errors import QueryCureError
from querycure.core.logging import get_logger
from querycure.db.repositories import agents as executions
from querycure.evidence.store import ensure_writable, list_evidence
from querycure.llm.structured import LLMError, call_structured
from querycure.llm.types import CallRecord, ChatMessage
from querycure.replay.artifact_store import get_artifact, link, store_json

log = get_logger(__name__)

OUTPUT_SCHEMA_VERSION = 1

type Judge[T] = Callable[[T, Mapping[str, str]], tuple[T, CitationReport]]


class AgentFailedError(QueryCureError):
    """The agent produced nothing usable; the run continues without its output."""

    code = "AGENT_FAILED"


@dataclass(frozen=True)
class AgentResult[T: BaseModel]:
    output: T
    report: CitationReport | None
    reused: bool


@dataclass
class _Row:
    record: CallRecord
    status: str
    error: dict[str, Any] | None = None


def _report_dict(report: CitationReport) -> dict[str, Any]:
    return {
        "total": report.total,
        "removed": report.removed,
        "stripped_ids": report.stripped_ids,
        "problems": report.problems,
    }


async def run_agent[T: BaseModel](
    ctx: RunContext,
    *,
    agent: str,
    node: str,
    invocation_key: str,
    prompt_version: str,
    messages: Sequence[ChatMessage],
    output_type: type[T],
    judge: Judge[T],
) -> AgentResult[T]:
    engine = ctx.db()
    async with engine.connect() as conn:
        reused = await _reuse(conn, ctx.run_id, invocation_key, output_type)
        if reused is not None:
            log.info("agent_output_reused", agent=agent, node=node)
            return AgentResult(output=reused, report=None, reused=True)
        attempt = await executions.attempts_so_far(conn, ctx.run_id, invocation_key)
        kinds = {e.id: e.kind for e in await list_evidence(conn, ctx.run_id)}

    clients = ctx.clients()
    rows: list[_Row] = []

    async def record_call(record: CallRecord) -> None:
        rows.append(_Row(record=record, status=record.status, error=_error(record)))
        await ctx.guard.record_tokens(
            input_tokens=record.input_tokens, output_tokens=record.output_tokens
        )

    conversation = list(messages)
    accepted: T | None = None
    report: CitationReport | None = None
    try:
        for citation_attempt in range(2):
            async with ctx.llm_slots:
                result = await call_structured(
                    clients.primary,
                    conversation,
                    output_type,
                    fallback=clients.fallback,
                    policy=ctx.llm_retry,
                    before_call=ctx.guard.charge_llm_call,
                    after_call=record_call,
                )
            cleaned, report = judge(result.value, kinds)
            if report.needs_retry and citation_attempt == 0:
                rows[-1].status = "invalid_output"
                rows[-1].error = {"code": "UNCITED_CLAIMS", "citations": _report_dict(report)}
                conversation += [
                    ChatMessage(role="assistant", content=result.raw_text),
                    feedback_message(report),
                ]
                continue
            if report.removed:
                log.warning(
                    "agent_claims_dropped",
                    agent=agent,
                    removed=report.removed,
                    total=report.total,
                )
            accepted = cleaned
            break
    except LLMError as exc:
        await _persist(ctx, agent, node, invocation_key, prompt_version, attempt, rows, None)
        raise AgentFailedError(
            f"The {agent} agent did not produce usable output.", details=[{"code": exc.code}]
        ) from None
    except BaseException:
        # Budget exhaustion or cancellation: keep the record of calls already made.
        await _persist(ctx, agent, node, invocation_key, prompt_version, attempt, rows, None)
        raise

    if accepted is None or report is None:
        raise AgentFailedError(f"The {agent} agent did not produce usable output.")
    stored = await _persist(
        ctx,
        agent,
        node,
        invocation_key,
        prompt_version,
        attempt,
        rows,
        {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "agent": agent,
            "node": node,
            "prompt_version": prompt_version,
            "model": rows[-1].record.model,
            "output": accepted.model_dump(mode="json"),
            "citations": _report_dict(report),
        },
    )
    if not stored:
        # Another worker recorded this invocation first; converge on its output.
        async with engine.connect() as conn:
            winner = await _reuse(conn, ctx.run_id, invocation_key, output_type)
        if winner is not None:
            return AgentResult(output=winner, report=None, reused=True)
    return AgentResult(output=accepted, report=report, reused=False)


def _error(record: CallRecord) -> dict[str, Any] | None:
    return {"code": record.error_code} if record.error_code else None


async def _reuse[T: BaseModel](
    conn: Any, run_id: uuid.UUID, invocation_key: str, output_type: type[T]
) -> T | None:
    sha = await executions.succeeded_output_sha(conn, run_id, invocation_key)
    if sha is None:
        return None
    artifact = await get_artifact(conn, sha)
    if artifact is None:
        return None
    return output_type.model_validate(json.loads(artifact.content)["output"])


async def _persist(
    ctx: RunContext,
    agent: str,
    node: str,
    invocation_key: str,
    prompt_version: str,
    attempt: int,
    rows: list[_Row],
    output: dict[str, Any] | None,
) -> bool:
    if not rows:
        return True
    async with ctx.db().begin() as conn:
        await ensure_writable(conn, ctx.run_id)
        artifact_id = None
        if output is not None:
            artifact = await store_json(conn, kind="agent_output", value=output)
            await link(
                conn,
                run_id=ctx.run_id,
                artifact_id=artifact.id,
                role="output.agent",
                produced_by=node,
            )
            artifact_id = artifact.id
        stored = True
        for i, row in enumerate(rows):
            final = output is not None and i == len(rows) - 1
            inserted = await executions.insert_execution(
                conn,
                run_id=ctx.run_id,
                agent=agent,
                node=node,
                invocation_key=invocation_key,
                attempt=attempt + i + 1,
                prompt_version=prompt_version,
                record=row.record,
                status="succeeded" if final else row.status,
                output_artifact_id=artifact_id if final else None,
                error=None if final else row.error,
            )
            if final:
                stored = inserted
    return stored
