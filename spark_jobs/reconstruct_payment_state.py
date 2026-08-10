"""Reconstruct payment state by producer transaction version, never arrival order."""

from __future__ import annotations

import argparse
import re

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _table(value: str) -> str:
    if TABLE_NAME.fullmatch(value) is None:
        raise ValueError(f"unsafe table identifier: {value}")
    return value


def reconstruct(events: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Reject an invalid transaction as a unit, then project only valid history."""
    transaction = Window.partitionBy("transaction_id")
    assessed = (
        events.withColumn(
            "version_count",
            F.count("*").over(Window.partitionBy("transaction_id", "transaction_version")),
        )
        .withColumn("version_conflict", F.max("version_count").over(transaction))
        .withColumn("transaction_event_count", F.count("*").over(transaction))
        .withColumn("minimum_version", F.min("transaction_version").over(transaction))
        .withColumn("maximum_version", F.max("transaction_version").over(transaction))
        .withColumn("currency_count", F.size(F.collect_set("currency").over(transaction)))
        .withColumn("processor_count", F.size(F.collect_set("processor_id").over(transaction)))
        .withColumn("merchant_count", F.size(F.collect_set("merchant_id").over(transaction)))
        .withColumn(
            "authorization_count",
            F.sum(F.when(F.col("event_type") == "authorization", 1).otherwise(0)).over(transaction),
        )
        .withColumn(
            "authorized_minor",
            F.max(F.when(F.col("event_type") == "authorization", F.col("amount_minor"))).over(
                transaction
            ),
        )
        .withColumn(
            "captured_minor",
            F.sum(
                F.when(F.col("event_type") == "capture", F.col("amount_minor")).otherwise(0)
            ).over(transaction),
        )
        .withColumn(
            "refunded_minor",
            F.sum(F.when(F.col("event_type") == "refund", F.col("amount_minor")).otherwise(0)).over(
                transaction
            ),
        )
        .withColumn(
            "chargeback_minor",
            F.sum(
                F.when(F.col("event_type") == "chargeback", F.col("amount_minor")).otherwise(0)
            ).over(transaction),
        )
        .withColumn(
            "authorization_version",
            F.min(
                F.when(F.col("event_type") == "authorization", F.col("transaction_version"))
            ).over(transaction),
        )
        .withColumn(
            "capture_version",
            F.min(F.when(F.col("event_type") == "capture", F.col("transaction_version"))).over(
                transaction
            ),
        )
        .withColumn(
            "reversal_version",
            F.min(
                F.when(
                    F.col("event_type").isin("refund", "chargeback"),
                    F.col("transaction_version"),
                )
            ).over(transaction),
        )
        .withColumn(
            "business_error",
            F.when(F.col("version_conflict") > 1, "transaction_version_conflict")
            .when(
                (F.col("minimum_version") != 1)
                | (F.col("maximum_version") != F.col("transaction_event_count")),
                "transaction_version_gap",
            )
            .when(F.col("currency_count") > 1, "currency_mutation")
            .when(F.col("processor_count") > 1, "processor_mutation")
            .when(F.col("merchant_count") > 1, "merchant_mutation")
            .when(F.col("authorization_count") > 1, "duplicate_authorization")
            .when(
                (F.col("authorization_count") == 0) & (F.col("captured_minor") > 0),
                "capture_without_authorization",
            )
            .when(F.col("authorization_count") == 0, "missing_authorization")
            .when(
                F.col("capture_version").isNotNull()
                & (F.col("capture_version") <= F.col("authorization_version")),
                "capture_before_authorization",
            )
            .when(
                F.col("reversal_version").isNotNull() & F.col("capture_version").isNull(),
                "reversal_without_capture",
            )
            .when(
                F.col("reversal_version").isNotNull()
                & (F.col("reversal_version") <= F.col("capture_version")),
                "reversal_before_capture",
            )
            .when(
                F.col("captured_minor") > F.col("authorized_minor"),
                "capture_exceeds_authorization",
            )
            .when(
                F.col("refunded_minor") + F.col("chargeback_minor") > F.col("captured_minor"),
                "refund_or_chargeback_exceeds_capture",
            ),
        )
    )
    exceptions = assessed.filter(F.col("business_error").isNotNull()).select(
        "event_id",
        "transaction_id",
        "transaction_version",
        "source_id",
        "processor_id",
        "merchant_id",
        "event_type",
        "amount_minor",
        "currency",
        "event_time",
        "received_at",
        "customer_token",
        "authorized_minor",
        "captured_minor",
        "refunded_minor",
        "chargeback_minor",
        "business_error",
        F.current_timestamp().alias("processed_at"),
    )
    valid = assessed.filter(F.col("business_error").isNull())
    latest = Window.partitionBy("transaction_id").orderBy(
        F.col("transaction_version").desc(), F.col("event_id").desc()
    )
    current = (
        valid.withColumn("state_rank", F.row_number().over(latest))
        .filter("state_rank=1")
        .select(
            "transaction_id",
            F.col("transaction_version").alias("current_version"),
            F.col("event_id").alias("current_event_id"),
            F.when(
                (F.col("captured_minor") > 0)
                & (F.col("refunded_minor") + F.col("chargeback_minor") == F.col("captured_minor"))
                & (F.col("chargeback_minor") > 0),
                "CHARGEDBACK",
            )
            .when(F.col("chargeback_minor") > 0, "PARTIALLY_CHARGEDBACK")
            .when(
                (F.col("captured_minor") > 0)
                & (F.col("refunded_minor") == F.col("captured_minor")),
                "REFUNDED",
            )
            .when(F.col("refunded_minor") > 0, "PARTIALLY_REFUNDED")
            .when(F.col("captured_minor") == F.col("authorized_minor"), "CAPTURED")
            .when(F.col("captured_minor") > 0, "PARTIALLY_CAPTURED")
            .otherwise("AUTHORIZED")
            .alias("status"),
            "authorized_minor",
            "captured_minor",
            "refunded_minor",
            "chargeback_minor",
            "currency",
            "processor_id",
            "merchant_id",
            F.current_timestamp().alias("processed_at"),
        )
    )
    return current, exceptions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--state-table", required=True)
    parser.add_argument("--exception-table", required=True)
    parser.add_argument("--business-date", required=True)
    args = parser.parse_args()
    spark = SparkSession.builder.appName("ledgerflow-payment-state").getOrCreate()
    source_table = _table(args.source_table)
    state_table = _table(args.state_table)
    exception_table = _table(args.exception_table)
    accepted = spark.table(source_table)
    touched_transactions = (
        accepted.filter(F.to_date("event_time") == F.to_date(F.lit(args.business_date)))
        .select("transaction_id")
        .distinct()
    )
    affected_history = accepted.join(touched_transactions, "transaction_id", "inner")
    current, exceptions = reconstruct(affected_history)
    current.createOrReplaceTempView("incoming_payment_state")
    exceptions.createOrReplaceTempView("incoming_business_exception")
    spark.sql(
        f"""
        MERGE INTO {state_table} target
        USING incoming_payment_state source ON target.transaction_id = source.transaction_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    spark.sql(
        f"""
        MERGE INTO {exception_table} target
        USING incoming_business_exception source ON target.event_id = source.event_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    spark.stop()


if __name__ == "__main__":
    main()
