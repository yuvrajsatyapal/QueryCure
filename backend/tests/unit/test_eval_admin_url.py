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


def test_an_explicit_admin_url_is_honoured() -> None:
    hosted = settings("postgresql://owner:pw@ep-x.aws.neon.tech/neondb")

    assert _admin_url(hosted, "postgresql://u:p@db.ci:5432/postgres") == (
        "postgresql://u:p@db.ci:5432/postgres"
    )
