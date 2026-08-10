{{ config(materialized='view') }}

select
    business_date,
    processor_id,
    currency,
    expected_minor,
    actual_minor,
    delta_minor,
    exception_reason,
    current_timestamp as refreshed_at
from {{ ref('stg_settlement_exception') }}
