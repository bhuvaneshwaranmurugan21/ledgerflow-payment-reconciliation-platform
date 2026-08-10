# ADR 0003: One retry owner per business step

Status: Accepted

EventBridge detects settlement-manifest delivery. One Step Functions execution owns manifest
validation, accepted-event ingestion, state reconstruction, posting, reconciliation and the
publication gate. Airflow waits for that gate and owns only dbt finance publication and controlled
backfills.

Glue jobs have zero platform retries; Step Functions applies bounded retries. This prevents two
orchestrators from multiplying retries or running the same financial mutation concurrently.
