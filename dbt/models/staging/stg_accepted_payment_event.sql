select
    event_id,
    transaction_id,
    transaction_version,
    processor_id,
    merchant_id,
    event_type,
    amount_minor,
    currency,
    event_time,
    received_at as processed_at
from {{ source('ledgerflow_silver', 'accepted_event') }}
