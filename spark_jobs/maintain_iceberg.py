"""Compact data files and expire old snapshots without weakening the audit window."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime, timedelta

from pyspark.sql import SparkSession

TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


def _table(value: str) -> str:
    if TABLE_NAME.fullmatch(value) is None:
        raise ValueError(f"unsafe table identifier: {value}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", required=True, help="Comma-separated catalog.database.table")
    parser.add_argument("--snapshot-retention-days", type=int, default=30)
    args = parser.parse_args()
    raw_tables = [value.strip() for value in args.tables.split(",") if value.strip()]
    if not raw_tables:
        raise ValueError("empty Iceberg table list")
    tables = [_table(value) for value in raw_tables]
    if args.snapshot_retention_days < 7:
        raise ValueError("snapshot retention cannot be shorter than seven days")
    cutoff = datetime.now(UTC) - timedelta(days=args.snapshot_retention_days)
    spark = SparkSession.builder.appName("ledgerflow-maintain-iceberg").getOrCreate()
    for table in tables:
        iceberg_table = table.removeprefix("glue_catalog.")
        # Both substitutions are allowlisted or generated locally, never raw SQL fragments.
        rewrite_sql = f"CALL glue_catalog.system.rewrite_data_files(table => '{iceberg_table}')"
        expire_sql = (
            f"CALL glue_catalog.system.expire_snapshots(table => '{iceberg_table}', "
            f"older_than => TIMESTAMP '{cutoff.strftime('%Y-%m-%d %H:%M:%S')}')"
        )  # nosec B608
        spark.sql(rewrite_sql)
        spark.sql(expire_sql)
    spark.stop()


if __name__ == "__main__":
    main()
