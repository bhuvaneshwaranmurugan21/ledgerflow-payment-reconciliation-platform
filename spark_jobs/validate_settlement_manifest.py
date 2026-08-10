"""Validate settlement record counts and currency control totals at distributed scale."""

from __future__ import annotations

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, LongType, StringType, StructField, StructType

SETTLEMENT_SCHEMA = StructType(
    [
        StructField("schema_version", StringType(), False),
        StructField("business_date", DateType(), False),
        StructField("processor_id", StringType(), False),
        StructField("currency", StringType(), False),
        StructField("amount_minor", LongType(), False),
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--business-date", required=True)
    args = parser.parse_args()
    spark = SparkSession.builder.appName("ledgerflow-validate-settlement-manifest").getOrCreate()
    manifest = (
        spark.read.option("multiline", True).json(args.manifest_path).first().asDict(recursive=True)
    )
    records = spark.read.schema(SETTLEMENT_SCHEMA).json(args.data_path)
    invalid_count = records.filter(
        F.col("schema_version").isNull()
        | (F.col("schema_version") != "1.0")
        | F.col("business_date").isNull()
        | (F.col("business_date") != F.to_date(F.lit(args.business_date)))
        | F.col("processor_id").isNull()
        | ~F.col("currency").isin("INR", "USD", "EUR", "GBP")
        | F.col("amount_minor").isNull()
    ).count()
    if invalid_count != 0:
        raise RuntimeError("settlement evidence contract gate failed")
    actual_count = records.count()
    duplicate_keys = (
        records.groupBy("business_date", "processor_id", "currency")
        .count()
        .filter("count > 1")
        .limit(1)
        .count()
    )
    if duplicate_keys != 0:
        raise RuntimeError("duplicate settlement evidence key")
    totals = {
        row["currency"]: row["amount_minor"]
        for row in records.groupBy("currency")
        .agg(F.sum("amount_minor").alias("amount_minor"))
        .collect()
    }
    if actual_count != manifest["record_count"]:
        raise RuntimeError("settlement manifest record-count gate failed")
    if totals != manifest["raw_control_totals_minor"]:
        raise RuntimeError("settlement manifest control-total gate failed")
    spark.stop()


if __name__ == "__main__":
    main()
