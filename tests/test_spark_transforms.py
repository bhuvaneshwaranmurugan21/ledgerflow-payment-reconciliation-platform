from __future__ import annotations

import pytest

pyspark = pytest.importorskip("pyspark")

from pyspark.sql import SparkSession  # noqa: E402

from spark_jobs.post_ledger import posting_lines  # noqa: E402
from spark_jobs.reconstruct_payment_state import reconstruct  # noqa: E402


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("ledgerflow-transform-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.python.use.daemon", "false")
        .config("spark.python.worker.reuse", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def lifecycle_rows() -> list[dict[str, object]]:
    base = {
        "transaction_id": "txn-1",
        "source_id": "gateway-01",
        "processor_id": "processor-01",
        "merchant_id": "merchant-01",
        "currency": "INR",
        "received_at": "2026-01-01T00:10:00Z",
        "customer_token": "token",
    }
    return [
        {
            **base,
            "event_id": "txn-1:v3",
            "transaction_version": 3,
            "event_type": "refund",
            "amount_minor": 2500,
            "event_time": "2026-01-01T00:03:00Z",
        },
        {
            **base,
            "event_id": "txn-1:v1",
            "transaction_version": 1,
            "event_type": "authorization",
            "amount_minor": 10000,
            "event_time": "2026-01-01T00:01:00Z",
        },
        {
            **base,
            "event_id": "txn-1:v2",
            "transaction_version": 2,
            "event_type": "capture",
            "amount_minor": 10000,
            "event_time": "2026-01-01T00:02:00Z",
        },
    ]


def test_out_of_order_state_is_reconstructed_by_version(spark: SparkSession) -> None:
    current, exceptions = reconstruct(spark.createDataFrame(lifecycle_rows()))
    state = current.first().asDict()
    assert exceptions.count() == 0
    assert state["current_version"] == 3
    assert state["status"] == "PARTIALLY_REFUNDED"
    assert state["captured_minor"] == 10000
    assert state["refunded_minor"] == 2500


def test_posting_lines_balance_per_event_and_currency(spark: SparkSession) -> None:
    events = spark.createDataFrame(lifecycle_rows()).filter("event_type <> 'authorization'")
    lines = posting_lines(events)
    balances = {
        (row["event_id"], row["currency"]): row["balance"]
        for row in lines.groupBy("event_id", "currency")
        .sum("signed_minor")
        .withColumnRenamed("sum(signed_minor)", "balance")
        .collect()
    }
    assert lines.count() == 4
    assert set(balances.values()) == {0}


def test_overcapture_quarantines_entire_transaction(spark: SparkSession) -> None:
    rows = lifecycle_rows()[:2]
    rows[0] = {
        **rows[0],
        "event_type": "capture",
        "amount_minor": 15_000,
        "transaction_version": 2,
    }
    rows[1] = {
        **rows[1],
        "event_type": "authorization",
        "amount_minor": 10_000,
        "transaction_version": 1,
    }
    current, exceptions = reconstruct(spark.createDataFrame(rows))
    assert current.count() == 0
    assert exceptions.count() == 2
    assert {row["business_error"] for row in exceptions.collect()} == {
        "capture_exceeds_authorization"
    }


def test_missing_transaction_version_blocks_projection(spark: SparkSession) -> None:
    rows = lifecycle_rows()
    rows = [row for row in rows if row["transaction_version"] != 2]
    current, exceptions = reconstruct(spark.createDataFrame(rows))
    assert current.count() == 0
    assert exceptions.count() == 2
    assert {row["business_error"] for row in exceptions.collect()} == {
        "transaction_version_gap"
    }
