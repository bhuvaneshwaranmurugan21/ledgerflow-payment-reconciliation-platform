"""Execute the canonical Iceberg DDL against the selected Glue database."""

from __future__ import annotations

import argparse
import re

from pyspark.sql import SparkSession

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _database(value: str) -> str:
    if IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"unsafe database identifier: {value}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--ddl-path", required=True)
    args = parser.parse_args()
    database = _database(args.database)
    spark = SparkSession.builder.appName("ledgerflow-bootstrap-iceberg").getOrCreate()
    source = spark.read.option("wholetext", True).text(args.ddl_path).first()["value"]
    rendered = source.replace("__DATABASE__", database)
    executable = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [statement.strip() for statement in executable.split(";") if statement.strip()]
    if len(statements) != 7:
        raise RuntimeError(f"expected seven Iceberg DDL statements, found {len(statements)}")
    database_sql = f"CREATE DATABASE IF NOT EXISTS glue_catalog.{database}"
    spark.sql(database_sql)
    for statement in statements:
        spark.sql(statement)
    spark.stop()


if __name__ == "__main__":
    main()
