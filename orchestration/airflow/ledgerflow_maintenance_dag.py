"""Airflow owns the weekly Iceberg maintenance window, outside finance publication."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.providers.amazon.aws.operators.glue import GlueJobOperator

with DAG(
    dag_id="ledgerflow_weekly_iceberg_maintenance",
    schedule="0 1 * * 0",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "payments-data",
        "retries": 0,
        "execution_timeout": timedelta(hours=4),
    },
    tags=["payments", "iceberg", "maintenance"],
) as dag:
    compact_and_expire = GlueJobOperator(
        task_id="compact_and_expire",
        job_name="{{ var.value.ledgerflow_maintenance_job }}",
        script_args={
            "--tables": "{{ var.value.ledgerflow_maintenance_tables }}",
            "--snapshot-retention-days": "{{ var.value.ledgerflow_snapshot_retention_days }}",
        },
        wait_for_completion=True,
        verbose=True,
    )
