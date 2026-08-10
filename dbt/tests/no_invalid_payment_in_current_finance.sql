select current_payment.transaction_id
from {{ ref('dim_payment_current') }} current_payment
inner join {{ ref('stg_business_exception') }} invalid
    on invalid.transaction_id = current_payment.transaction_id
