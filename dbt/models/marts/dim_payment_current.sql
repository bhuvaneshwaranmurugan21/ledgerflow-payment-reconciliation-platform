{{ config(materialized='view') }}

select
    transaction_id,
    current_version,
    current_event_id,
    status,
    authorized_minor,
    captured_minor,
    refunded_minor,
    chargeback_minor,
    captured_minor - refunded_minor - chargeback_minor as net_processor_receivable_minor,
    currency,
    processor_id,
    merchant_id,
    current_timestamp as refreshed_at
from {{ ref('stg_payment_state') }} state
where not exists (
    select 1
    from {{ ref('stg_business_exception') }} invalid
    where invalid.transaction_id = state.transaction_id
)
