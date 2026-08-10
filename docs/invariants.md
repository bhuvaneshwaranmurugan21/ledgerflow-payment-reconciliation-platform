# Financial invariants

## Identity grains

| Identifier | Grain | Purpose |
| --- | --- | --- |
| `event_id` | One producer business mutation | Idempotency and audit identity |
| `transaction_id` | One payment lifecycle | Current-state reconstruction |
| `transaction_version` | Ordered mutation inside a transaction | Deterministic state sequence |
| `entry_id` | One ledger line | Immutable double-entry detail |
| Settlement key | Date, processor and currency | Independent external reconciliation |

An event table and a current-state table are intentionally different. Multiple event IDs may
belong to one transaction. Ledger lines are append-only consequences of accepted events.

## Money

Money is represented as a signed integer in the currency's minor unit. Every ledger posting
group is bounded by one event and one currency and must sum to zero. Currency changes within a
transaction are business exceptions rather than implicit conversion.

## Lifecycle

The current-state projection sorts accepted events by `transaction_version`, then event time
and event ID as deterministic conflict diagnostics. Arrival order cannot change the projection.
Lifecycle validation is transaction-atomic: a conflicting or non-contiguous version, identity
mutation, missing authorization, over-capture or excessive reversal quarantines every event in that transaction
from state and ledger publication. Finance never receives a partial projection of an invalid
transaction. The automated settlement gate remains closed until evidence is corrected; any manual
finance exception is explicitly outside this repository's automated publication path.

## Reconciliation

Raw reconciliation classifies every arrival. Ledger reconciliation tests every posting group.
Settlement reconciliation compares an internally derived expectation with independently
delivered processor evidence. Infrastructure health cannot override a failed money gate.
