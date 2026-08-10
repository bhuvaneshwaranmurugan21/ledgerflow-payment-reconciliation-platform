# Operations and SLOs

## Service-level indicators

| SLI | Objective | Measurement |
| --- | --- | --- |
| Durable event ingestion | 99.9% monthly | Accepted durable writes / valid attempted writes |
| Durable accepted-evidence freshness | p95 under 10 minutes | Accepted-object time minus received time |
| Authoritative payment state | Before daily reconciliation | State job completion for the business date |
| Daily finance publication | By 04:00 UTC | Successful gated publication timestamp |
| Raw reconciliation | 100% | Accepted + duplicate + quarantined = arrivals |
| Ledger balance | Zero unbalanced event/currency groups | Ledger validation query |
| Settlement completeness | 100% or explicit exception | Expected versus external totals |

## Incident priority

- **SEV-1:** prohibited card data, unbalanced ledger, unexplained settlement delta or loss of raw
  evidence.
- **SEV-2:** missed state-completion cut-off, failed processor file or blocked daily publication.
- **SEV-3:** isolated producer quarantine increase without financial publication impact.

## Controlled replay

1. Freeze the input checksum and source range.
2. Record code, contract and posting-rule versions.
3. Run into isolated Iceberg snapshots.
4. Compare classification, ledger hashes, business totals and settlement deltas.
5. Publish atomically only after all gates pass.
6. Retain the before/after snapshots and run evidence.

## Iceberg maintenance

The weekly maintenance DAG compacts small files and expires snapshots older than the configured
audit window. Production retention cannot be set below seven days by the job; the normal setting is
30 days or the organization's longer financial-retention policy. Maintenance has its own Airflow
DAG and never runs inside the settlement publication transaction.
