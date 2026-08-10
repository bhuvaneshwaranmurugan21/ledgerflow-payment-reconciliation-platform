select
    event_id,
    currency,
    sum(signed_minor) as balance_minor
from {{ ref('stg_ledger_entry') }}
group by 1,2
having sum(signed_minor) <> 0

