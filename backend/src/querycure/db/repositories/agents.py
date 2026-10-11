import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.llm.types import CallRecord


async def succeeded_output_sha(
    conn: AsyncConnection, run_id: uuid.UUID, invocation_key: str
) -> str | None:
    return (
        await conn.execute(
            text(
                "SELECT a.sha256 FROM agent_executions e JOIN artifacts a "
                "ON a.id = e.output_artifact_id WHERE e.run_id = :run_id "
                "AND e.invocation_key = :key AND e.status = 'succeeded'"
            ),
            {"run_id": run_id, "key": invocation_key},
        )
    ).scalar_one_or_none()


async def attempts_so_far(conn: AsyncConnection, run_id: uuid.UUID, invocation_key: str) -> int:
    count = (
        await conn.execute(
            text(
                "SELECT count(*) FROM agent_executions "
                "WHERE run_id = :run_id AND invocation_key = :key"
            ),
            {"run_id": run_id, "key": invocation_key},
        )
    ).scalar_one()
    return int(count)


async def insert_execution(
    conn: AsyncConnection,
    *,
    id: uuid.UUID | None = None,
    run_id: uuid.UUID,
    agent: str,
    node: str,
    invocation_key: str,
    attempt: int,
    prompt_version: str,
    record: CallRecord,
    status: str,
    output_artifact_id: uuid.UUID | None = None,
    error: dict[str, Any] | None = None,
) -> bool:
    """False when a concurrent worker already recorded this invocation's success."""
    result = await conn.execute(
        text(
            "INSERT INTO agent_executions (id, run_id, agent, node, invocation_key, attempt, "
            "prompt_version, model, requested_model, served_by, input_tokens, output_tokens, "
            "latency_ms, status, output_artifact_id, error) VALUES (coalesce(:id, "
            "uuid_generate_v4()), :run_id, :agent, :node, :key, :attempt, :prompt_version, "
            ":model, :requested_model, :served_by, :input_tokens, :output_tokens, :latency_ms, "
            ":status, :artifact_id, CAST(:error AS JSONB)) "
            "ON CONFLICT (run_id, invocation_key) WHERE status = 'succeeded' DO NOTHING"
        ),
        {
            "id": id,
            "run_id": run_id,
            "agent": agent,
            "node": node,
            "key": invocation_key,
            "attempt": attempt,
            "prompt_version": prompt_version,
            "model": record.model,
            "requested_model": record.requested_model,
            "served_by": record.served_by,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "latency_ms": record.latency_ms,
            "status": status,
            "artifact_id": output_artifact_id,
            "error": json.dumps(error) if error is not None else None,
        },
    )
    return result.rowcount == 1


async def insert_tool_execution(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    agent_execution_id: uuid.UUID,
    tool: str,
    args: dict[str, Any],
    status: str,
    latency_ms: int,
    evidence_ids: list[str],
    error: dict[str, Any] | None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO tool_executions (agent_execution_id, run_id, tool, args, status, "
            "latency_ms, evidence_ids, error) VALUES (:exec_id, :run_id, :tool, "
            "CAST(:args AS JSONB), :status, :latency_ms, :evidence_ids, CAST(:error AS JSONB))"
        ),
        {
            "exec_id": agent_execution_id,
            "run_id": run_id,
            "tool": tool,
            "args": json.dumps(args),
            "status": status,
            "latency_ms": latency_ms,
            "evidence_ids": evidence_ids,
            "error": json.dumps(error) if error is not None else None,
        },
    )
