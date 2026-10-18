"""One LLM agent invocation: structured call, citation check with one retry, persistence.

Idempotent per `invocation_key`: if a successful execution is already recorded (a node
re-run after a crash), its stored output is returned and no LLM call is made. Every
provider call becomes an `agent_executions` row (failed / invalid_output / succeeded); only
the accepted one is `succeeded` and points at the stored output artifact.
"""

import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from querycure.agents.citations import CitationReport, feedback_message
from querycure.agents.claims_v2 import CHECKER_VERSION, claim_context
from querycure.agents.fencing import Fence
from querycure.agents.outputs import AgentAnalysis, AgentTurn, ToolCallTurn, judge_analysis
from querycure.agents.runtime import RunContext, ToolAllowanceLike
from querycure.agents.tools.base import Tool, ToolContext
from querycure.core.errors import BudgetExhaustedError, QueryCureError
from querycure.core.logging import get_logger
from querycure.db.repositories import agents as executions
from querycure.events.types import EventType
from querycure.evidence.sanitize import clean_args, clean_text
from querycure.evidence.store import ensure_writable, list_evidence, record_evidence
from querycure.llm.structured import (
    LLMError,
    LLMPaidUsageBlockedError,
    LLMQuotaExhaustedError,
    call_structured,
)
from querycure.llm.types import CallRecord, ChatMessage
from querycure.replay.artifact_store import get_artifact, link, store_json

log = get_logger(__name__)

OUTPUT_SCHEMA_VERSION = 1
MAX_CLAIM_PROBLEMS = 40

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
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _report_dict(report: CitationReport) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total": report.total,
        "removed": report.removed,
        "stripped_ids": report.stripped_ids,
        "problems": report.problems,
    }
    if report.claim_problems or report.claims_removed:
        # ADR-0026: what the deterministic grounding removed, kept with the output.
        out["claim_check"] = {
            "checker": CHECKER_VERSION,
            "removed_claims": report.claims_removed,
            "problems": report.claim_problems[:MAX_CLAIM_PROBLEMS],
        }
    return out


def _log_grounding(agent: str, report: CitationReport) -> None:
    if report.claim_problems:
        log.warning(
            "agent_claims_ungrounded",
            agent=agent,
            removed_claims=report.claims_removed,
            problems=len(report.claim_problems),
        )


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
                    before_call=ctx.before_llm_call,
                    after_call=record_call,
                    health=ctx.llm_health,
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
            _log_grounding(agent, report)
            accepted = cleaned
            break
    except LLMError as exc:
        await _persist(ctx, agent, node, invocation_key, prompt_version, attempt, rows, None)
        _stop_on_policy(exc)
        raise AgentFailedError(
            f"The {agent} agent did not produce usable output.",
            details=[{"code": exc.code, "cause": exc.cause}],
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


def _stop_on_policy(exc: LLMError) -> None:
    """Free quota exhausted or paid usage detected: stop the run gracefully (partial report)
    instead of letting other agents try and fail the same way (ADR-0016)."""
    if isinstance(exc, LLMQuotaExhaustedError | LLMPaidUsageBlockedError):
        raise BudgetExhaustedError(
            exc.message, details=[{"budget": "llm_free_tier", "code": exc.code}]
        ) from None


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


MAX_TOOL_AGENT_TURNS = 14
TOOL_BUDGET_NOTE = (
    "Your tool budget for this analysis is used up. Give your final analysis now, based on the "
    "evidence you have."
)


def _tool_reply(fence: Fence, tool: str, body: str) -> ChatMessage:
    return ChatMessage(
        role="user", content=f"Result of {tool}:\n" + fence.block("tool_result", body)
    )


async def _record_row(
    ctx: RunContext,
    *,
    agent: str,
    node: str,
    invocation_key: str,
    prompt_version: str,
    attempt: int,
    row: _Row,
) -> None:
    async with ctx.db().begin() as conn:
        await ensure_writable(conn, ctx.run_id)
        await executions.insert_execution(
            conn,
            id=row.id,
            run_id=ctx.run_id,
            agent=agent,
            node=node,
            invocation_key=invocation_key,
            attempt=attempt,
            prompt_version=prompt_version,
            record=row.record,
            status=row.status,
            error=row.error,
        )


async def _execute_tool(
    tctx: ToolContext,
    *,
    agent: str,
    call: ToolCallTurn,
    tools: Mapping[str, Tool],
    allowance: ToolAllowanceLike,
    execution_id: uuid.UUID,
) -> str:
    """Runs one requested tool and returns the text the model sees (fenced by the caller)."""
    ctx = tctx.run
    engine = ctx.db()
    started = time.monotonic()
    tool = tools.get(call.tool)
    status, evidence_ids, error, reply = "ok", [], None, ""
    safe_args = clean_args(call.args)
    await ctx.events.emit(
        EventType.TOOL_STARTED, {"tool": clean_text(call.tool, 64), "agent": agent}
    )
    if tool is None:
        status, error = "refused", {"code": "TOOL_NOT_ALLOWED"}
        reply = (
            f"Tool {clean_text(call.tool, 64)!r} is not available to you. Available tools: "
            + ", ".join(tools)
        )
    else:
        try:
            await allowance.charge()
            args = tool.input_model.model_validate(call.args)
            output = await tool.run(tctx, args)
            evidence_ids = await record_evidence(engine, ctx.run_id, output.evidence)
            lines = [f"[{e.id}] ({e.kind}) {e.summary}" for e in output.evidence]
            if output.note:
                lines.append(clean_text(output.note, 500))
            reply = "\n".join(lines) or "No matching evidence."
        except ValidationError as exc:
            status, error = "error", {"code": "INVALID_ARGUMENTS"}
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(args)'}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)[:5]
            )
            reply = f"Invalid arguments for {tool.name}: {problems}"
        except BudgetExhaustedError as exc:
            if exc.details and exc.details[0].get("budget") != "tool_calls_per_agent":
                raise  # the run-wide budget is gone: stop the run, not just this agent
            status, error, reply = "refused", {"code": "TOOL_BUDGET_EXHAUSTED"}, TOOL_BUDGET_NOTE
        except QueryCureError as exc:
            status, error = "error", {"code": exc.code}
            reply = f"{tool.name} failed ({exc.code}). Continue with the evidence you have."
    latency_ms = int((time.monotonic() - started) * 1000)
    async with engine.begin() as conn:
        await ensure_writable(conn, ctx.run_id)
        await executions.insert_tool_execution(
            conn,
            run_id=ctx.run_id,
            agent_execution_id=execution_id,
            tool=clean_text(call.tool, 64),
            args=safe_args,
            status=status,
            latency_ms=latency_ms,
            evidence_ids=evidence_ids,
            error=error,
        )
    await ctx.events.emit(
        EventType.TOOL_COMPLETED,
        {
            "tool": clean_text(call.tool, 64),
            "agent": agent,
            "status": status,
            "duration_ms": latency_ms,
            "evidence_ids": evidence_ids,
        },
    )
    return reply


async def run_tool_agent(
    tctx: ToolContext,
    *,
    agent: str,
    node: str,
    invocation_key: str,
    prompt_version: str,
    messages: Sequence[ChatMessage],
    tools: Mapping[str, Tool],
    query_sql: str | None = None,
) -> AgentResult[AgentAnalysis]:
    """A tool-using analyst: JSON turns of `call_tool` or `final` (AGENT_SYSTEM §2, §5).

    Rows are written as each provider call finishes, so tool_executions always reference an
    existing agent_executions row and a crash mid-loop leaves a complete trail.
    """
    ctx = tctx.run
    engine = ctx.db()
    async with engine.connect() as conn:
        reused = await _reuse(conn, ctx.run_id, invocation_key, AgentAnalysis)
        if reused is not None:
            log.info("agent_output_reused", agent=agent, node=node)
            return AgentResult(output=reused, report=None, reused=True)
        attempt = await executions.attempts_so_far(conn, ctx.run_id, invocation_key)

    clients = ctx.clients()
    fence = Fence()
    allowance = ctx.guard.tool_allowance()
    conversation = list(messages)
    pending: list[_Row] = []

    async def on_call(record: CallRecord) -> None:
        await ctx.guard.record_tokens(
            input_tokens=record.input_tokens, output_tokens=record.output_tokens
        )
        row = _Row(record=record, status=record.status, error=_error(record))
        if record.status == "succeeded":
            pending.append(row)  # its status depends on what the turn turns out to be
            return
        nonlocal attempt
        attempt += 1
        await _record_row(
            ctx,
            agent=agent,
            node=node,
            invocation_key=invocation_key,
            prompt_version=prompt_version,
            attempt=attempt,
            row=row,
        )

    citation_retry_used = False
    try:
        for _ in range(MAX_TOOL_AGENT_TURNS):
            async with ctx.llm_slots:
                result = await call_structured(
                    clients.primary,
                    conversation,
                    AgentTurn,
                    fallback=clients.fallback,
                    policy=ctx.llm_retry,
                    before_call=ctx.before_llm_call,
                    after_call=on_call,
                    health=ctx.llm_health,
                )
            row = pending.pop()
            step = result.value.root
            attempt += 1
            if isinstance(step, ToolCallTurn):
                row.status = "tool_call"
                await _record_row(
                    ctx,
                    agent=agent,
                    node=node,
                    invocation_key=invocation_key,
                    prompt_version=prompt_version,
                    attempt=attempt,
                    row=row,
                )
                reply = await _execute_tool(
                    tctx,
                    agent=agent,
                    call=step,
                    tools=tools,
                    allowance=allowance,
                    execution_id=row.id,
                )
                conversation += [
                    ChatMessage(role="assistant", content=result.raw_text),
                    _tool_reply(fence, clean_text(step.tool, 64), reply),
                ]
                continue

            async with engine.connect() as conn:
                evidence = await list_evidence(conn, ctx.run_id)
            kinds = {e.id: e.kind for e in evidence}
            claims = claim_context(evidence, query_sql=query_sql)
            cleaned, report = judge_analysis(step.analysis, kinds, claims)
            if report.needs_retry and not citation_retry_used:
                citation_retry_used = True
                row.status = "invalid_output"
                row.error = {"code": "UNCITED_CLAIMS", "citations": _report_dict(report)}
                await _record_row(
                    ctx,
                    agent=agent,
                    node=node,
                    invocation_key=invocation_key,
                    prompt_version=prompt_version,
                    attempt=attempt,
                    row=row,
                )
                conversation += [
                    ChatMessage(role="assistant", content=result.raw_text),
                    feedback_message(report),
                ]
                continue
            if report.removed:
                log.warning(
                    "agent_claims_dropped", agent=agent, removed=report.removed, total=report.total
                )
            _log_grounding(agent, report)
            stored = await _store_final(
                ctx,
                agent=agent,
                node=node,
                invocation_key=invocation_key,
                prompt_version=prompt_version,
                attempt=attempt,
                row=row,
                output={
                    "schema_version": OUTPUT_SCHEMA_VERSION,
                    "agent": agent,
                    "node": node,
                    "prompt_version": prompt_version,
                    "model": row.record.model,
                    "output": cleaned.model_dump(mode="json"),
                    "citations": _report_dict(report),
                },
            )
            if not stored:
                async with engine.connect() as conn:
                    winner = await _reuse(conn, ctx.run_id, invocation_key, AgentAnalysis)
                if winner is not None:
                    return AgentResult(output=winner, report=None, reused=True)
            return AgentResult(output=cleaned, report=report, reused=False)
    except LLMError as exc:
        _stop_on_policy(exc)
        raise AgentFailedError(
            f"The {agent} agent did not produce usable output.",
            details=[{"code": exc.code, "cause": exc.cause}],
        ) from None
    raise AgentFailedError(
        f"The {agent} agent did not finish within {MAX_TOOL_AGENT_TURNS} turns.",
        details=[{"code": "TOO_MANY_TURNS"}],
    )


async def _store_final(
    ctx: RunContext,
    *,
    agent: str,
    node: str,
    invocation_key: str,
    prompt_version: str,
    attempt: int,
    row: _Row,
    output: dict[str, Any],
) -> bool:
    async with ctx.db().begin() as conn:
        await ensure_writable(conn, ctx.run_id)
        artifact = await store_json(conn, kind="agent_output", value=output)
        await link(
            conn, run_id=ctx.run_id, artifact_id=artifact.id, role="output.agent", produced_by=node
        )
        return await executions.insert_execution(
            conn,
            id=row.id,
            run_id=ctx.run_id,
            agent=agent,
            node=node,
            invocation_key=invocation_key,
            attempt=attempt,
            prompt_version=prompt_version,
            record=row.record,
            status="succeeded",
            output_artifact_id=artifact.id,
        )
