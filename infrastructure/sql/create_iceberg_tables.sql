-- Canonical table grains. The deploy path executes the equivalent statements through
-- spark_jobs/bootstrap_tables.py after Terraform provisions the catalog and warehouse.

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.accepted_event (
  event_id string,
  transaction_id string,
  transaction_version bigint,
  source_id string,
  processor_id string,
  merchant_id string,
  event_type string,
  amount_minor bigint,
  currency string,
  event_time timestamp,
  received_at timestamp,
  customer_token string
) USING iceberg
PARTITIONED BY (days(event_time), bucket(32, processor_id))
TBLPROPERTIES ('format-version'='2', 'write.parquet.compression-codec'='zstd');

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.payment_state (
  transaction_id string,
  current_version bigint,
  current_event_id string,
  status string,
  authorized_minor bigint,
  captured_minor bigint,
  refunded_minor bigint,
  chargeback_minor bigint,
  currency string,
  processor_id string,
  merchant_id string,
  processed_at timestamp
) USING iceberg
PARTITIONED BY (bucket(64, transaction_id))
TBLPROPERTIES ('format-version'='2', 'write.parquet.compression-codec'='zstd');

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.business_exception (
  event_id string,
  transaction_id string,
  transaction_version bigint,
  source_id string,
  processor_id string,
  merchant_id string,
  event_type string,
  amount_minor bigint,
  currency string,
  event_time timestamp,
  received_at timestamp,
  customer_token string,
  authorized_minor bigint,
  captured_minor bigint,
  refunded_minor bigint,
  chargeback_minor bigint,
  business_error string,
  processed_at timestamp
) USING iceberg
PARTITIONED BY (days(event_time))
TBLPROPERTIES ('format-version'='2', 'write.parquet.compression-codec'='zstd');

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.posted_event (
  event_id string,
  transaction_id string,
  transaction_version bigint,
  source_id string,
  processor_id string,
  merchant_id string,
  event_type string,
  amount_minor bigint,
  currency string,
  event_time timestamp,
  received_at timestamp,
  customer_token string
) USING iceberg
PARTITIONED BY (days(event_time), bucket(32, processor_id))
TBLPROPERTIES ('format-version'='2', 'write.parquet.compression-codec'='zstd');

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.ledger_entry (
  entry_id string,
  event_id string,
  transaction_id string,
  processor_id string,
  merchant_id string,
  currency string,
  event_time timestamp,
  account string,
  signed_minor bigint,
  posting_rule_version int
) USING iceberg
PARTITIONED BY (days(event_time), bucket(32, processor_id))
TBLPROPERTIES ('format-version'='2', 'write.parquet.compression-codec'='zstd');

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.settlement_exception (
  business_date date,
  processor_id string,
  currency string,
  expected_minor bigint,
  actual_minor bigint,
  delta_minor bigint
) USING iceberg
PARTITIONED BY (business_date)
TBLPROPERTIES ('format-version'='2');

CREATE TABLE IF NOT EXISTS glue_catalog.__DATABASE__.settlement_evidence (
  business_date date,
  processor_id string,
  currency string,
  amount_minor bigint
) USING iceberg
PARTITIONED BY (business_date)
TBLPROPERTIES ('format-version'='2');

-- bootstrap_tables.py executes this file after replacing the database placeholder.
