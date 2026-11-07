"""Fixed-dataset templates in the sandbox provisioner (Part B, M5), against a fake admin
connection: what happens when the template is absent, and that a refused source creates nothing.
The database-backed build is in tests/security/test_fixed_dataset_loader.py and
tests/integration/test_fixed_dataset_template.py (run with the sandbox services)."""

from pathlib import Path
from typing import Any

import pytest
from psycopg import sql
from pydantic import SecretStr

from querycure.core.errors import SandboxUnavailableError
from querycure.sandbox.provisioner import (
    FIXED_TEMPLATE_BUILDER,
    TEMPLATE_BUILDER,
    SandboxLease,
    SandboxProvisioner,
    template_name,
)
from querycure.workloads.loader import FixedDatasetError
from querycure.workloads.registry import WorkloadRef

FIXED = WorkloadRef.parse("online_retail_ii@v1:data=b3471c34b273")
GENERATED = WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=42")


class FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeAdmin:
    """The sandbox admin connection: records statements, answers the template lookup."""

    def __init__(self, template_comment: str | None = None) -> None:
        self.statements: list[str] = []
        self.template_comment = template_comment

    def execute(self, query: Any, params: Any = None) -> FakeResult:
        text = query.as_string(None) if isinstance(query, sql.Composable) else str(query)
        self.statements.append(text)
        if "shobj_description" in text:
            return FakeResult((self.template_comment,) if self.template_comment else None)
        return FakeResult(None)

    def creates_or_drops_a_database(self) -> bool:
        return any(("CREATE DATABASE" in s or "DROP DATABASE" in s) for s in self.statements)


def lease_over(admin: FakeAdmin) -> SandboxLease:
    provisioner = SandboxProvisioner(
        admin_url=SecretStr("postgresql://admin@127.0.0.1:1/sandbox"),
        bench_password=SecretStr("unused"),
    )
    return SandboxLease(provisioner, admin)  # type: ignore[arg-type]


def test_a_fixed_ref_is_built_by_its_own_template_builder() -> None:
    assert FIXED_TEMPLATE_BUILDER != TEMPLATE_BUILDER
    assert template_name(FIXED) != template_name(GENERATED)
    assert template_name(FIXED).startswith("qc_tpl_")


def test_the_fixed_template_name_is_pinned() -> None:
    # A change here renames the template: every stored environment digest that names it moves.
    assert template_name(FIXED) == "qc_tpl_3debc6e8d342bef0"


def test_a_missing_fixed_template_without_a_source_says_how_to_build_it() -> None:
    admin = FakeAdmin()

    with pytest.raises(SandboxUnavailableError) as raised:
        lease_over(admin).ensure_template(FIXED)

    message = str(raised.value)
    assert str(FIXED) in message
    assert "python -m querycure.workloads build-template" in message
    assert "QC_DATASETS_DIR" in message
    assert not admin.creates_or_drops_a_database()


def test_a_built_fixed_template_is_reused_without_any_source() -> None:
    comment = f"{FIXED}|{FIXED_TEMPLATE_BUILDER}|abc123"
    admin = FakeAdmin(template_comment=comment)

    template = lease_over(admin).ensure_template(FIXED)

    assert (template.workload_id, template.data_digest) == (str(FIXED), "abc123")
    assert template.name == template_name(FIXED)
    assert not admin.creates_or_drops_a_database()


def test_a_template_from_another_builder_version_is_not_reused() -> None:
    admin = FakeAdmin(template_comment=f"{FIXED}|tpl-fixed@0|abc123")

    with pytest.raises(SandboxUnavailableError):
        lease_over(admin).ensure_template(FIXED)


def test_an_absent_source_file_is_refused_before_any_database_is_created(tmp_path: Path) -> None:
    admin = FakeAdmin()

    with pytest.raises(FixedDatasetError) as raised:
        lease_over(admin).ensure_template(FIXED, source=tmp_path / "absent.csv")

    assert raised.value.code == "DATA_FILE_MISSING"
    assert not admin.creates_or_drops_a_database()


def test_a_wrong_source_file_is_refused_before_any_database_is_created(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.csv"
    wrong.write_bytes(b"not the dataset")
    admin = FakeAdmin()

    with pytest.raises(FixedDatasetError) as raised:
        lease_over(admin).ensure_template(FIXED, source=wrong)

    assert raised.value.code == "DATA_FILE_SIZE"
    assert not admin.creates_or_drops_a_database()


def test_a_source_file_is_only_for_fixed_datasets(tmp_path: Path) -> None:
    admin = FakeAdmin()

    with pytest.raises(ValueError, match="fixed dataset"):
        lease_over(admin).ensure_template(GENERATED, source=tmp_path / "x.csv")

    assert not admin.creates_or_drops_a_database()
