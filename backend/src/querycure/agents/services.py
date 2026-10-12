"""Services nodes reach through the run context: live inspection for Mode B."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, ExitStack, asynccontextmanager
from typing import Protocol

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.connectors.credentials import target_from_record
from querycure.connectors.inspection_gateway import InspectionGateway
from querycure.connectors.models import (
    ActivityBucket,
    ExplainResult,
    LockBucket,
    SchemaSnapshot,
    StatementStat,
    TableIo,
    TargetCapabilities,
    TargetConnection,
)
from querycure.connectors.ssrf_guard import TargetPolicy
from querycure.core.config import Settings
from querycure.core.errors import ApprovalRequiredError, NotFoundError
from querycure.db.repositories.connections import get_connection
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.sql.validator import TableRef
from querycure.workloads.registry import WorkloadRef

CONTEXT_LEASE_SECONDS = 120.0


class Inspector(Protocol):
    async def capabilities(self) -> TargetCapabilities: ...
    async def explain(self, query: str) -> ExplainResult: ...
    async def schema_snapshot(self, tables: list[TableRef]) -> SchemaSnapshot: ...
    async def statement_stats(self, *, limit: int = 10) -> list[StatementStat]: ...
    async def activity_summary(self) -> list[ActivityBucket]: ...
    async def lock_summary(self) -> list[LockBucket]: ...
    async def table_io(self, tables: list[TableRef]) -> list[TableIo]: ...


class InspectorFactory(Protocol):
    def open(self, connection_id: uuid.UUID) -> AbstractAsyncContextManager[Inspector]: ...


class GatewayInspectorFactory:
    """Opens the hardened inspection gateway for a connection owned by the run's user."""

    def __init__(self, engine: AsyncEngine, settings: Settings, user_id: uuid.UUID) -> None:
        self._engine = engine
        self._settings = settings
        self._user_id = user_id

    @asynccontextmanager
    async def open(self, connection_id: uuid.UUID) -> AsyncIterator[Inspector]:
        async with self._engine.begin() as conn:
            record = await get_connection(conn, user_id=self._user_id, connection_id=connection_id)
        if record is None:
            raise NotFoundError("Connection not found.")
        if record.environment == "production":
            # Approval for production EXPLAIN arrives with the approval gate (Phase 3).
            raise ApprovalRequiredError("EXPLAIN on a production connection needs approval.")
        target = target_from_record(record, self._user_id, self._settings)
        async with InspectionGateway.open(
            target, policy=TargetPolicy.from_settings(self._settings)
        ) as gateway:
            yield gateway


@asynccontextmanager
async def sandbox_inspector(
    provisioner: SandboxProvisioner, *, workload_id: str, run_id: uuid.UUID
) -> AsyncIterator[Inspector]:
    """Mode C context: the hardened gateway (read-only session, timeouts, plain EXPLAIN only)
    on a throwaway clone of the workload template, as qc_bench. The template is built here
    if needed (AGENT_SYSTEM §6: speculative template build during analysis). The clone is
    dropped and the lease released on exit, whatever happens."""
    stack = ExitStack()
    lease = await asyncio.to_thread(
        stack.enter_context, provisioner.lease(timeout_seconds=CONTEXT_LEASE_SECONDS)
    )
    clone: str | None = None
    try:
        template = await asyncio.to_thread(lease.ensure_template, WorkloadRef.parse(workload_id))
        clone = await asyncio.to_thread(
            lease.create_clone, template, uuid.uuid5(run_id, "context"), 0
        )
        info = provisioner.bench_conninfo(clone)
        target = TargetConnection(
            host=str(info["host"]),
            port=int(info["port"]),
            dbname=clone,
            username=str(info["user"]),
            password=SecretStr(str(info["password"])),
            sslmode="disable",  # our own sandbox on an internal network / loopback relay
        )
        # The sandbox is QueryCure's own infrastructure, so private addresses are expected.
        policy = TargetPolicy(allow_private=True, allowed_ports=frozenset({int(info["port"])}))
        async with InspectionGateway.open(target, policy=policy) as gateway:
            yield gateway
    finally:
        if clone is not None:
            await asyncio.to_thread(lease.drop_clone, clone)
        await asyncio.to_thread(stack.close)
