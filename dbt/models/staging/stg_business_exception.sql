select distinct
    transaction_id,
    business_error,
    processed_at
from {{ source('ledgerflow_silver', 'business_exception') }}
