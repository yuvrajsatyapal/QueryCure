"""`python -m querycure.workloads build-template` (Part B, M5): local-only, verifies the file
first, never needs the worker container to have the data."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from querycure.sandbox.provisioner import Template, template_name
from querycure.workloads import __main__ as cli
from querycure.workloads.registry import WorkloadRef

REF = "online_retail_ii@v1:data=b3471c34b273"
URL = "postgresql://admin:pw@127.0.0.1:55432/sandbox_admin"


class FakeLease:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self.calls = calls

    def cleanup_orphans(self) -> list[str]:
        self.calls.append(("cleanup_orphans", None))
        return []

    def drop_template(self, ref: WorkloadRef) -> None:
        self.calls.append(("drop_template", str(ref)))

    def ensure_template(self, ref: WorkloadRef, source: Path | None = None) -> Template:
        self.calls.append(("ensure_template", (str(ref), source)))
        return Template(name=template_name(ref), workload_id=str(ref), data_digest="digest123")


class FakeProvisioner:
    instances: ClassVar[list["FakeProvisioner"]] = []

    def __init__(self, *, admin_url: SecretStr, bench_password: SecretStr, **_: Any) -> None:
        self.admin_url = admin_url.get_secret_value()
        self.password = bench_password.get_secret_value()
        self.calls: list[tuple[str, Any]] = []
        FakeProvisioner.instances.append(self)

    def bootstrap(self) -> None:
        self.calls.append(("bootstrap", None))

    @contextmanager
    def lease(self, *, timeout_seconds: float, **_: Any) -> Iterator[FakeLease]:
        self.calls.append(("lease", timeout_seconds))
        yield FakeLease(self.calls)


@pytest.fixture(autouse=True)
def fake_provisioner(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeProvisioner.instances.clear()
    monkeypatch.setattr(cli, "SandboxProvisioner", FakeProvisioner)
    monkeypatch.setenv("SANDBOX_BENCH_PASSWORD", "bench-secret")


def patched_ref() -> str:
    from querycure.workloads import registry

    fixed = registry.WORKLOADS["online_retail_ii"].fixed
    assert fixed is not None
    return f"online_retail_ii@v1:data={fixed.data_id}"


def pinned_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A file the registry accepts as the dataset: patch the pin to a tiny stand-in."""
    import hashlib

    from querycure.workloads import registry

    content = b"tiny stand-in for the dataset"
    path = tmp_path / "stand_in.csv"
    path.write_bytes(content)
    fixed = registry.WORKLOADS["online_retail_ii"].fixed
    assert fixed is not None
    patched = fixed.model_copy(
        update={"csv_sha256": hashlib.sha256(content).hexdigest(), "csv_bytes": len(content)}
    )
    monkeypatch.setitem(
        registry.WORKLOADS,
        "online_retail_ii",
        registry.WORKLOADS["online_retail_ii"].model_copy(update={"fixed": patched}),
    )
    return path


def test_a_non_local_sandbox_host_is_refused_before_anything_connects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = pinned_file(tmp_path, monkeypatch)

    with pytest.raises(SystemExit, match="only local sandboxes"):
        cli.main(
            [
                "build-template",
                "--sandbox-url",
                "postgresql://a:b@db.example.com/x",
                "--csv",
                str(path),
            ]
        )

    assert FakeProvisioner.instances == []


def test_the_bench_password_must_be_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = pinned_file(tmp_path, monkeypatch)
    monkeypatch.delenv("SANDBOX_BENCH_PASSWORD")

    code = cli.main(["build-template", "--sandbox-url", URL, "--csv", str(path)])

    assert code == 2
    assert "SANDBOX_BENCH_PASSWORD" in capsys.readouterr().err
    assert FakeProvisioner.instances == []


def test_a_missing_file_is_refused_before_any_connection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["build-template", "--sandbox-url", URL, "--csv", str(tmp_path / "absent.csv")])

    assert code == 1
    assert "DATA_FILE_MISSING" in capsys.readouterr().err
    assert FakeProvisioner.instances == []


def test_a_wrong_file_is_refused_before_any_connection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrong = tmp_path / "wrong.csv"
    wrong.write_bytes(b"not the dataset")

    code = cli.main(["build-template", "--sandbox-url", URL, "--csv", str(wrong)])

    assert code == 1
    assert "DATA_FILE_SIZE" in capsys.readouterr().err
    assert FakeProvisioner.instances == []


def test_a_generated_ref_has_no_template_to_build_from_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = pinned_file(tmp_path, monkeypatch)

    code = cli.main(
        [
            "build-template",
            "--sandbox-url",
            URL,
            "--csv",
            str(path),
            "--ref",
            "orders_ecommerce@v1:sf=1:seed=42",
        ]
    )

    assert code == 2
    assert "not a fixed dataset" in capsys.readouterr().err
    assert FakeProvisioner.instances == []


def test_the_template_is_built_from_the_verified_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = pinned_file(tmp_path, monkeypatch)

    code = cli.main(["build-template", "--sandbox-url", URL, "--csv", str(path)])

    assert code == 0
    (provisioner,) = FakeProvisioner.instances
    assert (provisioner.admin_url, provisioner.password) == (URL, "bench-secret")
    assert [name for name, _ in provisioner.calls] == [
        "bootstrap",
        "lease",
        "cleanup_orphans",
        "ensure_template",
    ]
    ref = patched_ref()
    assert provisioner.calls[-1][1] == (ref, path)
    printed = json.loads(capsys.readouterr().out)
    assert printed == {
        "template": template_name(WorkloadRef.parse(ref)),
        "workload_id": ref,
        "data_digest": "digest123",
    }


def test_rebuild_drops_the_old_template_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = pinned_file(tmp_path, monkeypatch)

    cli.main(["build-template", "--sandbox-url", URL, "--csv", str(path), "--rebuild"])

    (provisioner,) = FakeProvisioner.instances
    names = [name for name, _ in provisioner.calls]
    assert names.index("drop_template") < names.index("ensure_template")


def test_the_password_is_never_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = pinned_file(tmp_path, monkeypatch)

    cli.main(["build-template", "--sandbox-url", URL, "--csv", str(path)])

    captured = capsys.readouterr()
    assert "bench-secret" not in captured.out + captured.err
    assert "pw@" not in captured.out + captured.err


def test_the_default_csv_location_comes_from_the_datasets_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("QC_DATASETS_DIR", str(tmp_path))

    code = cli.main(["build-template", "--sandbox-url", URL])

    assert code == 1
    assert str(tmp_path / "online-retail-ii" / "online_retail_ii.csv") in capsys.readouterr().err


def test_loading_a_fixed_ref_into_an_empty_database_points_at_build_template(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["postgresql://u:p@127.0.0.1/x", REF])

    assert "build-template" in str(raised.value)
