from typing import Any

import psycopg
from psycopg import sql

from querycure.workloads.registry import WorkloadRef, build_statements


def load_workload(conn: psycopg.Connection[Any], ref: WorkloadRef) -> None:
    """Create and fill the workload's tables in one transaction on an empty database."""
    with conn.transaction():
        for statement in build_statements(ref):
            conn.execute(statement)  # composed with psycopg.sql: literals and identifiers only


def table_checksums(conn: psycopg.Connection[Any], tables: list[str]) -> dict[str, str]:
    """md5 over each table's rows in a stable order: equal checksums ⇔ identical data."""
    result: dict[str, str] = {}
    for table in tables:
        row = conn.execute(
            sql.SQL(
                "SELECT md5(coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), '')) FROM {} t"
            ).format(sql.Identifier(table))
        ).fetchone()
        result[table] = str(row[0]) if row else ""
    return result
