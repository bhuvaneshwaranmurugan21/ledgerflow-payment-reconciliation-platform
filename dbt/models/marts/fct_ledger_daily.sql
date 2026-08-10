{{ config(materialized='view') }}

select
    cast(event_time as date) as business_date,
    processor_id,
    merchant_id,
    currency,
    account,
    count(*) as entry_count,
    sum(signed_minor) as signed_minor,
    current_timestamp as refreshed_at
from {{ ref('stg_ledger_entry') }} ledger
where not exists (
    select 1
    from {{ ref('stg_business_exception') }} invalid
    where invalid.transaction_id = ledger.transaction_id
)
group by 1,2,3,4,5
