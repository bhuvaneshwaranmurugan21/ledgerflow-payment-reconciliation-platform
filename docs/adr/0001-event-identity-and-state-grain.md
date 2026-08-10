# ADR 0001: Separate event identity from payment state

Status: Accepted

`event_id` identifies one immutable business mutation. `transaction_id` identifies a payment and
`transaction_version` orders its lifecycle. Arrival time is retained for operations but cannot
select financial truth.

This prevents the common grain error where one payment key is used both to deduplicate events and
to overwrite current state. Exact event replay becomes a no-op; changed payload under the same
event ID is quarantined; current state is a deterministic projection of accepted history.
