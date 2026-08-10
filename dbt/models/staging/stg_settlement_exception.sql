select
    business_date,
    processor_id,
    currency,
    expected_minor,
    actual_minor,
    delta_minor,
    'settlement_delta' as exception_reason,
    cast(business_date as timestamp) as processed_at
from {{ source('ledgerflow_silver', 'settlement_exception') }}
