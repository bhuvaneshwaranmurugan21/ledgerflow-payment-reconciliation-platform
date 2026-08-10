select *
from {{ ref('fct_settlement_exception') }}
where delta_minor = 0
