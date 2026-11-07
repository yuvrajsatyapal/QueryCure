"""Demo workload tools.

Load a generated workload into an empty database you own:

    python -m querycure.workloads URL WORKLOAD_ID

Build the sandbox template of a fixed (real) dataset, once, on this machine:

    SANDBOX_BENCH_PASSWORD=... python -m querycure.workloads build-template \
        --sandbox-url postgresql://...@127.0.0.1:55432/sandbox_admin [--csv FILE] [--rebuild]

`build-template` is local-only (it creates and drops databases, like the repeatability study) and
reads the data file from `$QC_DATASETS_DIR` (default `~/Datasets/QueryCure`) unless `--csv` is
given. The file is verified against its pinned SHA-256 before anything touches the database. The
worker container never needs the file: it only uses the finished template.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from pydantic import SecretStr

from querycure.benchmark.repeatability import check_local
from querycure.core.errors import QueryCureError
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.workloads.loader import (
    FixedDatasetError,
    default_csv_path,
    load_workload,
    table_checksums,
    verified_source,
)
from querycure.workloads.registry import WORKLOADS, WorkloadRef

BENCH_PASSWORD_ENV = "SANDBOX_BENCH_PASSWORD"  # noqa: S105 (the name of an env var, not a secret)
LEASE_TIMEOUT_SECONDS = 600.0  # a template build is one long, exclusive job


def _default_fixed_ref() -> str:
    for spec in WORKLOADS.values():
        if spec.fixed is not None:
            return f"{spec.name}@v{spec.version}:data={spec.fixed.data_id}"
    raise RuntimeError("no fixed dataset is registered")


def _load(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("url", help="postgresql:// URL of an empty database you own")
    parser.add_argument("workload", help="e.g. orders_ecommerce@v1:sf=0.1:seed=42")
    args = parser.parse_args(argv)
    ref = WorkloadRef.parse(args.workload)
    if WORKLOADS[ref.name].fixed is not None:
        raise SystemExit(
            f"{ref} is a fixed dataset, not generated: build its sandbox template with "
            "`python -m querycure.workloads build-template` instead."
        )
    with psycopg.connect(args.url, autocommit=True) as conn:
        load_workload(conn, ref)
        checksums = table_checksums(conn, WORKLOADS[ref.name].tables)
    print(json.dumps({"workload": str(ref), "checksums": checksums}, indent=2))
    return 0


def _build_template(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m querycure.workloads build-template", description=_build_template.__doc__
    )
    parser.add_argument("--sandbox-url", required=True, help="admin URL of a LOCAL sandbox server")
    parser.add_argument("--ref", default=_default_fixed_ref(), help="the fixed dataset reference")
    parser.add_argument("--csv", type=Path, default=None, help="the data file (default: see above)")
    parser.add_argument("--rebuild", action="store_true", help="drop an existing template first")
    args = parser.parse_args(argv)
    check_local(args.sandbox_url)
    ref = WorkloadRef.parse(args.ref)
    fixed = WORKLOADS[ref.name].fixed
    if fixed is None:
        print(f"{ref} is not a fixed dataset: nothing to build from a file.", file=sys.stderr)
        return 2
    password = os.environ.get(BENCH_PASSWORD_ENV)
    if not password:
        print(
            f"{BENCH_PASSWORD_ENV} must be set (the sandbox bench role's password).",
            file=sys.stderr,
        )
        return 2
    csv_path = args.csv or default_csv_path(fixed)
    try:
        with verified_source(csv_path, fixed):  # refuse a wrong file before connecting anywhere
            pass
        provisioner = SandboxProvisioner(
            admin_url=SecretStr(args.sandbox_url), bench_password=SecretStr(password)
        )
        provisioner.bootstrap()
        with provisioner.lease(timeout_seconds=LEASE_TIMEOUT_SECONDS) as lease:
            lease.cleanup_orphans()
            if args.rebuild:
                lease.drop_template(ref)
            template = lease.ensure_template(ref, source=csv_path)
    except FixedDatasetError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    except QueryCureError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "template": template.name,
                "workload_id": template.workload_id,
                "data_digest": template.data_digest,
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["build-template"]:
        return _build_template(args[1:])
    return _load(args)


if __name__ == "__main__":
    raise SystemExit(main())
