"""Load a demo workload into an empty database: python -m querycure.workloads URL WORKLOAD_ID"""

import argparse
import json

import psycopg

from querycure.workloads.loader import load_workload, table_checksums
from querycure.workloads.registry import WORKLOADS, WorkloadRef


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="postgresql:// URL of an empty database you own")
    parser.add_argument("workload", help="e.g. orders_ecommerce@v1:sf=0.1:seed=42")
    args = parser.parse_args()
    ref = WorkloadRef.parse(args.workload)
    with psycopg.connect(args.url, autocommit=True) as conn:
        load_workload(conn, ref)
        checksums = table_checksums(conn, WORKLOADS[ref.name].tables)
    print(json.dumps({"workload": str(ref), "checksums": checksums}, indent=2))


if __name__ == "__main__":
    main()
