# ADR 0002: Integer minor units and balanced posting groups

Status: Accepted

All monetary fields are signed integers in the currency's declared minor unit. Each financial event
produces a versioned posting group whose lines sum to zero for that event and currency. Refunds and
chargebacks append compensating entries rather than modifying prior history.

This costs additional storage and modeling effort but makes rounding behavior explicit, provides an
auditable trail and turns ledger balance into an executable invariant.
