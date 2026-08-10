"""Airflow owns daily finance publication and controlled backfills only."""

from __future__ import annotations

from datetime import timedelta

import boto3
import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.sensors.python import PythonSensor


def active_revision_is_reconciled(business_date: str, table_name: str) -> bool:
    """Read the authoritative date gate, not an eventually stale object marker."""
    item = boto3.client("dynamodb").get_item(
        TableName=table_name,
        Key={"business_date": {"S": business_date}},
        ConsistentRead=True,
    ).get("Item", {})
    return item.get("publication_status", {}).get("S") == "RECONCILED"

with DAG(
    dag_id="ledgerflow_daily_finance",
    schedule="30 2 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "payments-data",
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(hours=1),
    },
    tags=["payments", "finance", "reconciliation"],
) as dag:
    wait_for_gate = PythonSensor(
        task_id="wait_for_reconciliation_gate",
        python_callable=active_revision_is_reconciled,
        op_kwargs={
            "business_date": "{{ data_interval_start | ds }}",
            "table_name": "{{ var.value.settlement_publication_table }}",
        },
        timeout=60 * 60,
        poke_interval=60,
        mode="reschedule",
    )

    publish = BashOperator(
        task_id="publish_finance_marts",
        bash_command=(
            "cd /opt/airflow/dbt && dbt source freshness --target prod "
            "&& dbt build --target prod "
            "--vars '{business_date: {{ data_interval_start | ds }}}'"
        ),
    )

    wait_for_gate >> publish
