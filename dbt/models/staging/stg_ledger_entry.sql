select
    entry_id,
    event_id,
    transaction_id,
    processor_id,
    merchant_id,
    currency,
    account,
    signed_minor,
    event_time,
    posting_rule_version,
    event_time as processed_at
from {{ source('ledgerflow_silver', 'ledger_entry') }}
