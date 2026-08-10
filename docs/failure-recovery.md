# Failure and recovery model

| Failure | Detection | Publication effect | Recovery |
| --- | --- | --- | --- |
| Exact event replay | Identity fingerprint match | No second financial effect | Record duplicate metric |
| Identity reserved, S3 publish interrupted | DynamoDB status remains `PENDING` | No downstream visibility yet | Retry reuses the same identity, rewrites the deterministic object and marks `PUBLISHED` |
| Event ID with altered payload | Identity conflict | Quarantine event | Producer correction with new identity |
| Corrupt settlement file | Manifest checksum | Workflow stops before ingestion | Redeliver checksum-protected file |
| Settlement object changes after verification | Version-bound server-side copy | Checked bytes remain the processed bytes | Deliver a higher manifest revision |
| Capture without authorization | Lifecycle reconstruction | Exclude event from ledger | Resolve producer sequence or rule |
| Unbalanced posting rule | Rule validation | Deployment and publication blocked | Publish reviewed rule version |
| Crash before transaction commit | Run journal and rollback | No partial ledger/state effect | Retry immutable input |
| Settlement mismatch | Processor/date/currency delta | Finance marts blocked | Explain or correct external evidence |
| Late evidence after cut-off | Freshness SLI | Prior day remains provisional | Controlled republish |
| Older revision finishes after a correction | Conditional publication registry | Older workflow becomes `Superseded` | No operator action unless the active revision fails |
| Late lifecycle event invalidates prior state | Current business-exception overlay | Prior projection disappears from finance views | Correct source history, then controlled rebuild |
| Prohibited card field | Schema gate | Quarantine and security alert | Remove field and investigate producer |

Replay evidence binds the input checksum, run ID, posting-rule version, implementation checksum, ledger
count and current-state hash. A retry is successful only when it preserves financial state.

The identity table is a small publication journal, not just a deduplication set. Reserving an
identity and publishing its deterministic accepted object are separately recoverable steps.
Finance-facing dbt models are views so that a newly discovered transaction-level exception takes
effect immediately; the Iceberg event and ledger history remains available for audit and repair.
