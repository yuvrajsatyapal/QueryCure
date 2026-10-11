from alembic import context
from sqlalchemy import engine_from_config, pool

from querycure.core.config import Settings

config = context.config


def _url() -> str:
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    settings = Settings()
    if settings.database_migration_url is None:
        raise RuntimeError("DATABASE_MIGRATION_URL (owner role) is required to run migrations")
    url = settings.database_migration_url.get_secret_value()
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_online() -> None:
    engine = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=None, transaction_per_migration=True
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
