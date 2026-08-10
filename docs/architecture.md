# Architecture and responsibility boundaries

## Source systems

Payment gateways, operational payment databases, bank/FX APIs and processor settlement files
are external producers. LedgerFlow owns their contracts and ingestion evidence, not their
transactional availability.

## Ingestion

- Kinesis lifecycle topics carry low-latency application events.
- DMS emits standard CDC envelopes only from append-only `payment_outbox` tables. The shared
  contract layer unwraps `insert`/`load` records and rejects updates, deletes and unrelated tables.
- The manifest loader validates the small manifest, object name, byte size and S3-managed SHA-256
  without downloading a large object. It server-side copies the exact checked S3 version into a
  verified-input bucket, eliminating a head/read time-of-check race. The first distributed Glue
  step verifies record count and currency control totals before downstream work.
- The schema and identity gate separates exact replay from conflicting reuse of an event ID.
- S3 bronze is the immutable recovery boundary; cursor advancement follows durable persistence.

## Financial processing

Spark reconstructs payment lifecycle state from producer transaction versions. Glue jobs apply
versioned posting rules, create balanced lines and derive processor settlement expectations.
The reconciliation gate checks source classification, transaction exceptions, per-event ledger
balance and external settlement totals before finance publication.

Daily processing reads only the accepted S3 partition for the requested business date. State and
posting jobs identify transactions touched on that date, then retrieve their complete immutable
history so late lifecycle events remain correct without an unbounded full-history recomputation.

## Storage and serving

Iceberg tables preserve accepted events, current state, ledger lines, settlement evidence and
exceptions as distinct grains. dbt creates finance and risk marts in Redshift. Athena access is
restricted to audit queries over governed Iceberg data.

Ledger and state tables retain historical projections, while finance dbt views apply the current
business-exception overlay at read time. This prevents a later lifecycle violation from leaving a
previously materialized finance row visible. Materialization is a measured optimization decision,
not a correctness shortcut.

## Orchestration ownership

- EventBridge detects a manifested settlement delivery and starts Step Functions.
- Step Functions owns file validation, ledger posting, settlement reconciliation and the
  publication decision for one settlement file.
- Airflow owns scheduled daily dbt publication and controlled historical backfills.

Processor feeds are consolidated into one manifested dataset per business date and revision. The
active revision is held in DynamoDB. Only a workflow whose revision and manifest hash are still
active can transition the date to `RECONCILED`; a late completion from an older revision becomes
`Superseded`. Airflow reads this authoritative record rather than trusting a stale file marker.

The same business step does not receive retries from two orchestrators.

## Traceability

[`architecture-manifest.json`](architecture-manifest.json) is executable documentation. CI
fails when an internal architecture component does not point to at least one retained artifact.
