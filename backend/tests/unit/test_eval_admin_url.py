import pytest
from pydantic import SecretStr

from querycure.core.config import Settings
from querycure.evals.__main__ import _admin_url


def settings(migration_url: str) -> Settings:
    return Settings(_env_file=None, database_migration_url=SecretStr(migration_url))


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_a_local_owner_url_is_used_for_scratch_databases(host: str) -> None:
    url = _admin_url(settings(f"postgresql://owner:pw@{host}:5432/querycure"), None)

    assert url == f"postgresql://owner:pw@{host}:5432/postgres"


def test_a_hosted_owner_url_is_refused_without_an_explicit_admin_url() -> None:
    # Evals create and drop databases; a .env pointing at a hosted metadata DB (Neon) must
    # never be used for that implicitly.
    hosted = settings("postgresql://owner:pw@ep-x.aws.neon.tech/neondb?sslmode=require")

    with pytest.raises(SystemExit, match="--admin-url"):
        _admin_url(hosted, None)


@pytest.mark.parametrize(
    "url",
    ["postgresql://u:p@127.0.0.1:5432/postgres", "postgresql://u:p@metadata-db:5432/postgres"],
)
def test_an_explicit_local_admin_url_is_honoured(url: str) -> None:
    hosted = settings("postgresql://owner:pw@ep-x.aws.neon.tech/neondb")

    assert _admin_url(hosted, url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://owner:pw@ep-x-pooler.aws.neon.tech/neondb?sslmode=require",
        "postgresql://u:p@db.ci:5432/postgres",
        "postgresql://u:p@10.0.0.5:5432/postgres",
    ],
)
def test_an_explicit_remote_admin_url_is_refused(url: str) -> None:
    # 2026-10-18: evals CREATE and DROP scratch databases, so even an explicit URL must be a
    # local server; a typo or a pasted Neon URL must never reach a hosted database.
    with pytest.raises(SystemExit, match="local"):
        _admin_url(settings("postgresql://o:p@127.0.0.1/querycure"), url)
