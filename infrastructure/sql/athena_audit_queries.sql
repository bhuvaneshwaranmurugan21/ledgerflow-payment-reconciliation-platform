-- 1. This query must return no rows before finance publication.
SELECT event_id, currency, SUM(signed_minor) AS balance_minor
FROM __DATABASE__.ledger_entry
GROUP BY event_id, currency
HAVING SUM(signed_minor) <> 0;

-- 2. Daily independent settlement differences.
SELECT business_date, processor_id, currency,
       expected_minor, actual_minor, delta_minor
FROM __DATABASE__.settlement_exception
WHERE business_date = DATE '2026-01-01'
ORDER BY ABS(delta_minor) DESC;

-- 3. Trace a payment without exposing customer identifiers.
SELECT transaction_id, transaction_version, event_type, amount_minor,
       currency, event_time, processor_id
FROM __DATABASE__.accepted_event
WHERE transaction_id = 'replace-with-approved-transaction-id'
ORDER BY transaction_version;
