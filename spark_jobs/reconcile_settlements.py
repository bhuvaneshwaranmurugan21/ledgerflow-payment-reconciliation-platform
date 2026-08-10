"""Compare independent processor evidence with internal ledger expectations."""

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
    parser.add_argument("--posted-event-table", required=True)
    parser.add_argument("--business-exception-table", required=True)
    parser.add_argument("--settlement-path", required=True)
    parser.add_argument("--settlement-evidence-table", required=True)
    parser.add_argument("--exception-table", required=True)
    parser.add_argument("--business-date", required=True)
    args = parser.parse_args()
    spark = SparkSession.builder.appName("ledgerflow-settlement-reconciliation").getOrCreate()
    posted_event_table = _table(args.posted_event_table)
    business_exception_table = _table(args.business_exception_table)
    evidence_table = _table(args.settlement_evidence_table)
    exception_table = _table(args.exception_table)
    invalid_transactions = spark.table(business_exception_table).select("transaction_id").distinct()
    posted = (
        spark.table(posted_event_table)
        .join(invalid_transactions, "transaction_id", "left_anti")
        .filter(F.to_date("event_time") == F.to_date(F.lit(args.business_date)))
    )
    expected = posted.groupBy(
        F.to_date("event_time").alias("business_date"), "processor_id", "currency"
    ).agg(
        F.sum(
            F.when(F.col("event_type") == "capture", F.col("amount_minor"))
            .when(F.col("event_type").isin("refund", "chargeback"), -F.col("amount_minor"))
            .otherwise(0)
        ).alias("expected_minor")
    )
    actual = (
        spark.read.json(args.settlement_path)
        .withColumn("business_date", F.to_date("business_date"))
        .select(
            "business_date",
            "processor_id",
            "currency",
            F.col("amount_minor").alias("actual_minor"),
        )
    )
    actual.createOrReplaceTempView("incoming_settlement_evidence")
    # Spark SQL cannot bind table identifiers; _table applies a strict segment allowlist.
    evidence_merge_sql = (
        f"MERGE INTO {evidence_table} target\n"  # nosec B608
        "USING incoming_settlement_evidence source\n"
        "  ON target.business_date = source.business_date\n"
        " AND target.processor_id = source.processor_id\n"
        " AND target.currency = source.currency\n"
        "WHEN MATCHED THEN UPDATE SET target.amount_minor = source.actual_minor\n"
        "WHEN NOT MATCHED THEN INSERT "
        "(business_date, processor_id, currency, amount_minor)\n"
        "VALUES (source.business_date, source.processor_id, source.currency, "
        "source.actual_minor)"
    )
    spark.sql(evidence_merge_sql)
    exceptions = (
        expected.join(actual, ["business_date", "processor_id", "currency"], "full")
        .fillna(0, subset=["expected_minor", "actual_minor"])
        .withColumn("delta_minor", F.col("expected_minor") - F.col("actual_minor"))
        .filter("delta_minor <> 0")
    )
    exceptions.writeTo(exception_table).overwrite(
        F.col("business_date") == F.to_date(F.lit(args.business_date))
    )
    if exceptions.limit(1).count() != 0:
        raise RuntimeError("settlement reconciliation gate failed")
    spark.stop()


if __name__ == "__main__":
    main()
