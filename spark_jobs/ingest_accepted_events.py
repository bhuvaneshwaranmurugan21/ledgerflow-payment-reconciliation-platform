"""Merge contract-approved event objects into the Iceberg accepted-event table."""

from __future__ import annotations

import argparse
import re

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


def _table(value: str) -> str:
    if TABLE_NAME.fullmatch(value) is None:
        raise ValueError(f"unsafe table identifier: {value}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--target-table", required=True)
    args = parser.parse_args()
    target_table = _table(args.target_table)
    spark = SparkSession.builder.appName("ledgerflow-ingest-accepted-events").getOrCreate()
    incoming = spark.read.json(args.source_path).select(
        "event_id",
        "transaction_id",
        F.col("transaction_version").cast("long").alias("transaction_version"),
        "source_id",
        "processor_id",
        "merchant_id",
        "event_type",
        F.col("amount_minor").cast("long").alias("amount_minor"),
        "currency",
        F.to_timestamp("event_time").alias("event_time"),
        F.to_timestamp("received_at").alias("received_at"),
        "customer_token",
    )
    incoming.createOrReplaceTempView("incoming_accepted_event")
    # Spark SQL cannot bind table identifiers; _table applies a strict segment allowlist.
    merge_sql = f"""
        MERGE INTO {target_table} target
        USING incoming_accepted_event source ON target.event_id = source.event_id
        WHEN NOT MATCHED THEN INSERT *
        """
    spark.sql(merge_sql)
    spark.stop()


if __name__ == "__main__":
    main()
