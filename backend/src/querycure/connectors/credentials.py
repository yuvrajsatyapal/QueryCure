"""Turning a stored connection into a TargetConnection: shared by the API and the worker."""

import uuid

from querycure.connectors.models import TargetConnection
from querycure.core.config import Settings
from querycure.core.crypto import SecretBox, secret_aad
from querycure.core.errors import ConfigurationError, NotFoundError
from querycure.db.repositories.connections import ConnectionRecord

CONNECTIONS_TABLE = "database_connections"


def secret_box(settings: Settings) -> SecretBox:
    if settings.master_key is None:
        raise ConfigurationError("QC_MASTER_KEY is not configured; credentials cannot be stored.")
    return SecretBox.from_base64(
        settings.master_key.get_secret_value(), version=settings.master_key_version
    )


def connection_aad(record_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    return secret_aad(table=CONNECTIONS_TABLE, row_id=str(record_id), user_id=str(user_id))


def target_from_record(
    record: ConnectionRecord, user_id: uuid.UUID, settings: Settings
) -> TargetConnection:
    """Decrypts the password; the plaintext lives only inside the returned SecretStr."""
    sealed = record.sealed_password()
    if sealed is None:
        raise NotFoundError("Connection not found.")
    password = secret_box(settings).decrypt(sealed, aad=connection_aad(record.id, user_id))
    return TargetConnection(
        host=record.host,
        port=record.port,
        dbname=record.dbname,
        username=record.username,
        password=password,
        sslmode=record.sslmode,  # type: ignore[arg-type]
    )
