"""Apply versioned double-entry rules and idempotently merge ledger lines."""

from __future__ import annotations

import argparse
import re

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _table(value: str) -> str:
    if TABLE_NAME.fullmatch(value) is None:
        raise ValueError(f"unsafe table identifier: {value}")
    return value


def posting_lines(events: DataFrame) -> DataFrame:
    monetary = events.filter(F.col("event_type").isin("capture", "refund", "chargeback"))
    debit_account = (
        F.when(F.col("event_type") == "capture", "processor_receivable")
        .when(F.col("event_type") == "refund", "merchant_payable")
        .otherwise("chargeback_loss")
    )
    credit_account = F.when(F.col("event_type") == "capture", "merchant_payable").otherwise(
        "processor_receivable"
    )
    debit = monetary.select(
        F.concat_ws(":", "event_id", F.lit("1")).alias("entry_id"),
        "event_id",
        "transaction_id",
        "processor_id",
        "merchant_id",
        "currency",
        "event_time",
        debit_account.alias("account"),
        F.col("amount_minor").alias("signed_minor"),
        F.lit(1).alias("posting_rule_version"),
    )
    credit = monetary.select(
        F.concat_ws(":", "event_id", F.lit("2")).alias("entry_id"),
        "event_id",
        "transaction_id",
        "processor_id",
        "merchant_id",
        "currency",
        "event_time",
        credit_account.alias("account"),
        (-F.col("amount_minor")).alias("signed_minor"),
        F.lit(1).alias("posting_rule_version"),
    )
    lines = debit.unionByName(credit)
    unbalanced = (
        lines.groupBy("event_id", "currency")
        .agg(F.sum("signed_minor").alias("balance"))
        .filter("balance <> 0")
    )
    if unbalanced.limit(1).count() != 0:
        raise RuntimeError("double-entry gate failed")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--exception-table", required=True)
    parser.add_argument("--posted-event-table", required=True)
    parser.add_argument("--ledger-table", required=True)
    parser.add_argument("--business-date", required=True)
    args = parser.parse_args()
    spark = SparkSession.builder.appName("ledgerflow-post-ledger").getOrCreate()
    source_table = _table(args.source_table)
    exception_table = _table(args.exception_table)
    posted_event_table = _table(args.posted_event_table)
    ledger_table = _table(args.ledger_table)
    accepted = spark.table(source_table)
    touched_transactions = (
        accepted.filter(F.to_date("event_time") == F.to_date(F.lit(args.business_date)))
        .select("transaction_id")
        .distinct()
    )
    affected_history = accepted.join(touched_transactions, "transaction_id", "inner")
    valid_events = affected_history.join(
        spark.table(exception_table).select("event_id"), "event_id", "left_anti"
    )
    monetary_events = valid_events.filter(
        F.col("event_type").isin("capture", "refund", "chargeback")
    )
    lines = posting_lines(monetary_events)
    monetary_events.createOrReplaceTempView("incoming_posted_events")
    lines.createOrReplaceTempView("incoming_ledger_lines")
    spark.sql(
        f"""
        MERGE INTO {posted_event_table} target
        USING incoming_posted_events source ON target.event_id = source.event_id
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    spark.sql(
        f"""
        MERGE INTO {ledger_table} target
        USING incoming_ledger_lines source ON target.entry_id = source.entry_id
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    spark.stop()


if __name__ == "__main__":
    main()
