select
    transaction_id,
    current_version,
    current_event_id,
    status,
    authorized_minor,
    captured_minor,
    refunded_minor,
    chargeback_minor,
    currency,
    processor_id,
    merchant_id,
    processed_at
from {{ source('ledgerflow_silver', 'payment_state') }}

