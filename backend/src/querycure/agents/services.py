"""Services nodes reach through the run context: live inspection for Mode B."""

import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.connectors.credentials import target_from_record
from querycure.connectors.inspection_gateway import InspectionGateway
from querycure.connectors.models import ExplainResult, SchemaSnapshot, TargetCapabilities
from querycure.connectors.ssrf_guard import TargetPolicy
from querycure.core.config import Settings
from querycure.core.errors import ApprovalRequiredError, NotFoundError
from querycure.db.repositories.connections import get_connection
from querycure.sql.validator import TableRef


class Inspector(Protocol):
    async def capabilities(self) -> TargetCapabilities: ...
    async def explain(self, query: str) -> ExplainResult: ...
    async def schema_snapshot(self, tables: list[TableRef]) -> SchemaSnapshot: ...


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
