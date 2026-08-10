"""Transactional identity gate, deterministic projections and financial ledger."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ledgerflow.contracts import (
    ContractError,
    PaymentEvent,
    Source,
    canonical_json,
    identity_fingerprint,
    redact_payload,
    sha256_text,
    validate_event,
)
from ledgerflow.ledger import PostingRules, build_postings

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS run_journal(
  run_id TEXT PRIMARY KEY,
  input_sha256 TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('STARTED','SUCCEEDED','FAILED')),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  failure_reason TEXT
);
CREATE TABLE IF NOT EXISTS run_outcome(
  run_id TEXT NOT NULL REFERENCES run_journal(run_id),
  outcome TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  record_count INTEGER NOT NULL,
  PRIMARY KEY(run_id, outcome, reason)
);
CREATE TABLE IF NOT EXISTS seen_event(
  event_id TEXT PRIMARY KEY,
  identity_sha256 TEXT NOT NULL,
  first_run_id TEXT NOT NULL REFERENCES run_journal(run_id)
);
CREATE TABLE IF NOT EXISTS accepted_event(
  event_id TEXT PRIMARY KEY REFERENCES seen_event(event_id),
  transaction_id TEXT NOT NULL,
  transaction_version INTEGER NOT NULL,
  source_id TEXT NOT NULL,
  processor_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
  currency TEXT NOT NULL,
  event_time TEXT NOT NULL,
  received_at TEXT NOT NULL,
  customer_token TEXT,
  safe_payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS accepted_event_transaction_idx
  ON accepted_event(transaction_id, transaction_version, event_time, event_id);
CREATE TABLE IF NOT EXISTS quarantine(
  quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES run_journal(run_id),
  event_id TEXT,
  reason TEXT NOT NULL,
  redacted_payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_exception(
  event_id TEXT PRIMARY KEY REFERENCES accepted_event(event_id),
  transaction_id TEXT NOT NULL,
  reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posted_event(
  event_id TEXT PRIMARY KEY REFERENCES accepted_event(event_id),
  transaction_id TEXT NOT NULL,
  processor_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  event_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_entry(
  entry_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES posted_event(event_id),
  transaction_id TEXT NOT NULL,
  processor_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  account TEXT NOT NULL,
  signed_minor INTEGER NOT NULL,
  posting_rule_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_state(
  transaction_id TEXT PRIMARY KEY,
  current_version INTEGER NOT NULL,
  current_event_id TEXT NOT NULL,
  status TEXT NOT NULL,
  authorized_minor INTEGER NOT NULL,
  captured_minor INTEGER NOT NULL,
  refunded_minor INTEGER NOT NULL,
  chargeback_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  processor_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settlement_actual(
  business_date TEXT NOT NULL,
  processor_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  PRIMARY KEY(business_date, processor_id, currency)
);
CREATE TABLE IF NOT EXISTS settlement_exception(
  business_date TEXT NOT NULL,
  processor_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  expected_minor INTEGER NOT NULL,
  actual_minor INTEGER NOT NULL,
  delta_minor INTEGER NOT NULL,
  PRIMARY KEY(business_date, processor_id, currency)
);
"""

TABLE_COUNT_QUERIES = {
    "accepted_event": "SELECT COUNT(*) FROM accepted_event",
    "quarantine": "SELECT COUNT(*) FROM quarantine",
    "business_exception": "SELECT COUNT(*) FROM business_exception",
    "posted_event": "SELECT COUNT(*) FROM posted_event",
    "ledger_entry": "SELECT COUNT(*) FROM ledger_entry",
    "payment_state": "SELECT COUNT(*) FROM payment_state",
}


def _event_from_row(row: sqlite3.Row) -> PaymentEvent:
    return PaymentEvent(
        schema_version="1.0",
        event_id=row["event_id"],
        transaction_id=row["transaction_id"],
        transaction_version=row["transaction_version"],
        source_id=row["source_id"],
        processor_id=row["processor_id"],
        merchant_id=row["merchant_id"],
        event_type=row["event_type"],
        amount_minor=row["amount_minor"],
        currency=row["currency"],
        event_time=row["event_time"],
        received_at=row["received_at"],
        customer_token=row["customer_token"],
    )


class LedgerStore:
    """SQLite evidence implementation of the production transaction boundaries."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.executescript(SCHEMA)
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def process(
        self,
        *,
        run_id: str,
        input_sha256: str,
        raw_events: Iterable[dict[str, Any]],
        registry: dict[str, Source],
        token_key: bytes,
        posting_rules: PostingRules,
        failpoint: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now(UTC).isoformat()
        with closing(self.connect()) as connection:
            connection.execute(
                "INSERT INTO run_journal VALUES (?, ?, 'STARTED', ?, NULL, NULL)",
                (run_id, input_sha256, started_at),
            )
            connection.commit()
            counts: Counter[tuple[str, str]] = Counter()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for raw in raw_events:
                    counts[("ARRIVAL", "raw_record_read")] += 1
                    self._ingest_one(connection, run_id, raw, registry, token_key, counts)
                if failpoint == "after_identity_gate":
                    raise RuntimeError("injected_failure:after_identity_gate")
                self._rebuild_projections(connection, posting_rules)
                if failpoint == "before_commit":
                    raise RuntimeError("injected_failure:before_commit")
                for (outcome, reason), count in sorted(counts.items()):
                    connection.execute(
                        "INSERT INTO run_outcome VALUES (?, ?, ?, ?)",
                        (run_id, outcome, reason, count),
                    )
                connection.commit()
            except Exception as error:
                connection.rollback()
                connection.execute(
                    "UPDATE run_journal SET status='FAILED', completed_at=?, failure_reason=? "
                    "WHERE run_id=?",
                    (datetime.now(UTC).isoformat(), str(error), run_id),
                )
                connection.commit()
                raise
            connection.execute(
                "UPDATE run_journal SET status='SUCCEEDED', completed_at=? WHERE run_id=?",
                (datetime.now(UTC).isoformat(), run_id),
            )
            connection.commit()
        return self.summary(run_id)

    @staticmethod
    def _ingest_one(
        connection: sqlite3.Connection,
        run_id: str,
        raw: dict[str, Any],
        registry: dict[str, Source],
        token_key: bytes,
        counts: Counter[tuple[str, str]],
    ) -> None:
        event_id = raw.get("event_id") if isinstance(raw.get("event_id"), str) else None
        try:
            event = validate_event(raw, registry, token_key)
        except ContractError as error:
            counts[("QUARANTINED", error.reason)] += 1
            connection.execute(
                "INSERT INTO quarantine(run_id,event_id,reason,redacted_payload_json) "
                "VALUES (?, ?, ?, ?)",
                (run_id, event_id, error.reason, canonical_json(redact_payload(raw))),
            )
            return
        fingerprint = identity_fingerprint(raw)
        existing = connection.execute(
            "SELECT identity_sha256 FROM seen_event WHERE event_id=?", (event.event_id,)
        ).fetchone()
        if existing is not None:
            if existing["identity_sha256"] == fingerprint:
                counts[("DUPLICATE", "exact_event_replay")] += 1
            else:
                reason = "identity_payload_conflict"
                counts[("QUARANTINED", reason)] += 1
                connection.execute(
                    "INSERT INTO quarantine(run_id,event_id,reason,redacted_payload_json) "
                    "VALUES (?, ?, ?, ?)",
                    (run_id, event.event_id, reason, canonical_json(redact_payload(raw))),
                )
            return
        safe = event.safe_dict()
        connection.execute(
            "INSERT INTO seen_event VALUES (?, ?, ?)", (event.event_id, fingerprint, run_id)
        )
        connection.execute(
            """
            INSERT INTO accepted_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.transaction_id,
                event.transaction_version,
                event.source_id,
                event.processor_id,
                event.merchant_id,
                event.event_type,
                event.amount_minor,
                event.currency,
                event.event_time,
                event.received_at,
                event.customer_token,
                canonical_json(safe),
            ),
        )
        counts[("ACCEPTED", "contract_and_identity_passed")] += 1

    @staticmethod
    def _rebuild_projections(connection: sqlite3.Connection, rules: PostingRules) -> None:
        connection.execute("DELETE FROM settlement_exception")
        connection.execute("DELETE FROM settlement_actual")
        connection.execute("DELETE FROM ledger_entry")
        connection.execute("DELETE FROM posted_event")
        connection.execute("DELETE FROM business_exception")
        connection.execute("DELETE FROM payment_state")
        transaction_ids = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT transaction_id FROM accepted_event ORDER BY transaction_id"
            )
        ]
        for transaction_id in transaction_ids:
            rows = connection.execute(
                """
                SELECT * FROM accepted_event WHERE transaction_id=?
                ORDER BY transaction_version, event_time, event_id
                """,
                (transaction_id,),
            ).fetchall()
            LedgerStore._project_transaction(connection, rows, rules)

    @staticmethod
    def _project_transaction(
        connection: sqlite3.Connection, rows: list[sqlite3.Row], rules: PostingRules
    ) -> None:
        events = [_event_from_row(row) for row in rows]
        if not events:
            return
        versions = [event.transaction_version for event in events]
        currencies = {event.currency for event in events}
        processors = {event.processor_id for event in events}
        merchants = {event.merchant_id for event in events}
        authorizations = [event for event in events if event.event_type == "authorization"]
        captures = [event for event in events if event.event_type == "capture"]
        reversals = [event for event in events if event.event_type in {"refund", "chargeback"}]
        authorized = sum(event.amount_minor for event in authorizations)
        captured = sum(event.amount_minor for event in captures)
        refunded = sum(event.amount_minor for event in events if event.event_type == "refund")
        charged_back = sum(
            event.amount_minor for event in events if event.event_type == "chargeback"
        )
        reason: str | None = None
        if len(set(versions)) != len(versions):
            reason = "transaction_version_conflict"
        elif min(versions) != 1 or max(versions) != len(versions):
            reason = "transaction_version_gap"
        elif len(currencies) != 1:
            reason = "currency_mutation"
        elif len(processors) != 1:
            reason = "processor_mutation"
        elif len(merchants) != 1:
            reason = "merchant_mutation"
        elif len(authorizations) > 1:
            reason = "duplicate_authorization"
        elif not authorizations and captures:
            reason = "capture_without_authorization"
        elif not authorizations:
            reason = "missing_authorization"
        elif (
            captures
            and min(event.transaction_version for event in captures)
            <= authorizations[0].transaction_version
        ):
            reason = "capture_before_authorization"
        elif reversals and not captures:
            reason = "reversal_without_capture"
        elif reversals and min(event.transaction_version for event in reversals) <= min(
            event.transaction_version for event in captures
        ):
            reason = "reversal_before_capture"
        elif captured > authorized:
            reason = "capture_exceeds_authorization"
        elif refunded + charged_back > captured:
            reason = "refund_or_chargeback_exceeds_capture"
        if reason is not None:
            for event in events:
                connection.execute(
                    "INSERT INTO business_exception VALUES (?, ?, ?)",
                    (event.event_id, event.transaction_id, reason),
                )
            return
        for event in events:
            postings = build_postings(event, rules)
            if postings:
                connection.execute(
                    "INSERT INTO posted_event VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.transaction_id,
                        event.processor_id,
                        event.merchant_id,
                        event.event_type,
                        event.amount_minor,
                        event.currency,
                        event.event_time,
                    ),
                )
            for line in postings:
                connection.execute(
                    "INSERT INTO ledger_entry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        line.entry_id,
                        line.event_id,
                        line.transaction_id,
                        line.processor_id,
                        line.merchant_id,
                        line.currency,
                        line.account,
                        line.signed_minor,
                        line.posting_rule_version,
                    ),
                )
        current = events[-1]
        if charged_back > 0:
            status = (
                "CHARGEDBACK" if refunded + charged_back == captured else "PARTIALLY_CHARGEDBACK"
            )
        elif refunded > 0:
            status = "REFUNDED" if refunded == captured else "PARTIALLY_REFUNDED"
        elif captured > 0:
            status = "CAPTURED" if captured == authorized else "PARTIALLY_CAPTURED"
        else:
            status = "AUTHORIZED"
        connection.execute(
            "INSERT INTO payment_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                current.transaction_id,
                current.transaction_version,
                current.event_id,
                status,
                authorized,
                captured,
                refunded,
                charged_back,
                current.currency,
                current.processor_id,
                current.merchant_id,
            ),
        )

    def expected_settlement(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT substr(event_time,1,10) AS business_date, processor_id, currency,
                  SUM(CASE
                    WHEN event_type='capture' THEN amount_minor
                    WHEN event_type IN ('refund','chargeback') THEN -amount_minor
                    ELSE 0 END) AS amount_minor
                FROM posted_event
                GROUP BY 1,2,3 ORDER BY 1,2,3
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def reconcile_settlement(self, actual: Iterable[dict[str, Any]]) -> dict[str, Any]:
        actual_materialized = list(actual)
        with closing(self.connect()) as connection:
            connection.execute("DELETE FROM settlement_actual")
            connection.execute("DELETE FROM settlement_exception")
            for row in actual_materialized:
                connection.execute(
                    "INSERT INTO settlement_actual VALUES (?, ?, ?, ?)",
                    (
                        row["business_date"],
                        row["processor_id"],
                        row["currency"],
                        row["amount_minor"],
                    ),
                )
            expected_rows = connection.execute(
                """
                SELECT substr(event_time,1,10) AS business_date, processor_id, currency,
                  SUM(CASE
                    WHEN event_type='capture' THEN amount_minor
                    WHEN event_type IN ('refund','chargeback') THEN -amount_minor
                    ELSE 0 END) AS amount_minor
                FROM posted_event
                GROUP BY 1,2,3 ORDER BY 1,2,3
                """
            ).fetchall()
            expected = {
                (row["business_date"], row["processor_id"], row["currency"]): row["amount_minor"]
                for row in expected_rows
            }
            actual_rows = {
                (row["business_date"], row["processor_id"], row["currency"]): row["amount_minor"]
                for row in actual_materialized
            }
            for key in sorted(expected.keys() | actual_rows.keys()):
                expected_minor = expected.get(key, 0)
                actual_minor = actual_rows.get(key, 0)
                delta = expected_minor - actual_minor
                if delta != 0:
                    connection.execute(
                        "INSERT INTO settlement_exception VALUES (?, ?, ?, ?, ?, ?)",
                        (*key, expected_minor, actual_minor, delta),
                    )
            connection.commit()
            exception_count = connection.execute(
                "SELECT COUNT(*) FROM settlement_exception"
            ).fetchone()[0]
            absolute_delta = connection.execute(
                "SELECT COALESCE(SUM(ABS(delta_minor)),0) FROM settlement_exception"
            ).fetchone()[0]
        return {
            "settlement_reconciled": exception_count == 0,
            "settlement_exception_count": exception_count,
            "settlement_absolute_delta_minor": absolute_delta,
        }

    def summary(self, run_id: str) -> dict[str, Any]:
        with closing(self.connect()) as connection:
            outcomes = {
                f"{row['outcome']}:{row['reason']}": row["record_count"]
                for row in connection.execute(
                    "SELECT outcome,reason,record_count FROM run_outcome WHERE run_id=?",
                    (run_id,),
                )
            }
            counts = {
                name: connection.execute(query).fetchone()[0]
                for name, query in TABLE_COUNT_QUERIES.items()
            }
            unbalanced = connection.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT event_id,currency FROM ledger_entry
                  GROUP BY event_id,currency HAVING SUM(signed_minor)<>0
                )
                """
            ).fetchone()[0]
            total_balance = connection.execute(
                "SELECT COALESCE(SUM(signed_minor),0) FROM ledger_entry"
            ).fetchone()[0]
            states = [
                tuple(row)
                for row in connection.execute("SELECT * FROM payment_state ORDER BY transaction_id")
            ]
            accepted_new = outcomes.get("ACCEPTED:contract_and_identity_passed", 0)
            duplicates = outcomes.get("DUPLICATE:exact_event_replay", 0)
            quarantined = sum(
                count for key, count in outcomes.items() if key.startswith("QUARANTINED:")
            )
            raw_records = outcomes.get("ARRIVAL:raw_record_read", 0)
        return {
            "classification": "MEASURED_LOCAL_RESULT",
            "run_id": run_id,
            "raw_records": raw_records,
            "accepted_new": accepted_new,
            "duplicates": duplicates,
            "quarantined": quarantined,
            "raw_reconciled": raw_records == accepted_new + duplicates + quarantined,
            **counts,
            "unbalanced_posting_groups": unbalanced,
            "ledger_balance_minor": total_balance,
            "ledger_balanced": unbalanced == 0 and total_balance == 0,
            "payment_state_sha256": sha256_text(canonical_json(states)),
            "outcomes": outcomes,
        }

    def table_count(self, table: str) -> int:
        query = TABLE_COUNT_QUERIES.get(table)
        if query is None:
            raise ValueError(f"unsupported table: {table}")
        with closing(self.connect()) as connection:
            return int(connection.execute(query).fetchone()[0])

    def clear_email_leak_count(self) -> int:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT safe_payload_json FROM accepted_event").fetchall()
        return sum("customer_email" in row[0] or "@" in row[0] for row in rows)
