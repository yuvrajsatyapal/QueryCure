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
            "INSERT INTO agent_executions (run_id, agent, node, invocation_key, attempt, "
            "prompt_version, model, input_tokens, output_tokens, latency_ms, status, "
            "output_artifact_id, error) VALUES (:run_id, :agent, :node, :key, :attempt, "
            ":prompt_version, :model, :input_tokens, :output_tokens, :latency_ms, :status, "
            ":artifact_id, CAST(:error AS JSONB)) "
            "ON CONFLICT (run_id, invocation_key) WHERE status = 'succeeded' DO NOTHING"
        ),
        {
            "run_id": run_id,
            "agent": agent,
            "node": node,
            "key": invocation_key,
            "attempt": attempt,
            "prompt_version": prompt_version,
            "model": record.model,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "latency_ms": record.latency_ms,
            "status": status,
            "artifact_id": output_artifact_id,
            "error": json.dumps(error) if error is not None else None,
        },
    )
    return result.rowcount == 1
