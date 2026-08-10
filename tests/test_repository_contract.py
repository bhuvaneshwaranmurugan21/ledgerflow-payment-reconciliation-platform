from __future__ import annotations

import json
from pathlib import Path


def test_step_function_definition_is_valid_json_and_has_one_publish_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    definition = json.loads(
        (root / "orchestration/stepfunctions/settlement_workflow.asl.json").read_text()
    )
    states = definition["States"]
    assert definition["StartAt"] == "ValidateSettlementManifest"
    assert list(states).count("PublishGate") == 1
    assert states["ReconcileSettlement"]["Next"] == "BuildPublicationEvidence"
    assert states["BuildPublicationEvidence"]["Next"] == "WritePublicationEvidence"
    assert states["WritePublicationEvidence"]["Next"] == "PublishGate"
    assert states["PublishGate"]["End"] is True
    assert (
        states["WritePublicationEvidence"]["Parameters"]["Body.$"]
        == "States.JsonToString($.publication_evidence)"
    )
    assert states["PublishGate"]["Parameters"]["ConditionExpression"] == (
        "revision = :revision AND manifest_sha256 = :sha"
    )

    glue_tasks = [
        "ValidateSettlementManifest",
        "IngestAcceptedEvents",
        "RunPaymentStateReconstruction",
        "PostLedger",
        "ReconcileSettlement",
    ]
    for name in glue_tasks:
        assert states[name]["ResultPath"].startswith("$.")
        assert states[name]["Catch"][0]["Next"] == "WorkflowFailed"

    post_args = states["PostLedger"]["Parameters"]["Arguments"]
    ingest_args = states["IngestAcceptedEvents"]["Parameters"]["Arguments"]
    state_args = states["RunPaymentStateReconstruction"]["Parameters"]["Arguments"]
    reconcile_args = states["ReconcileSettlement"]["Parameters"]["Arguments"]
    assert "event_date={}" in ingest_args["--source-path.$"]
    assert state_args["--business-date.$"] == "$.business_date"
    assert post_args["--business-date.$"] == "$.business_date"
    assert "--business-exception-table" not in post_args
    assert reconcile_args["--business-exception-table"] == "${business_exception_table}"

    validation_args = states["ValidateSettlementManifest"]["Parameters"]["Arguments"]
    assert "$.verified_bucket" in validation_args["--data-path.$"]
    assert "$.manifest_bucket" in validation_args["--manifest-path.$"]


def test_canonical_iceberg_ddl_is_parameterized_and_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    ddl = (root / "infrastructure/sql/create_iceberg_tables.sql").read_text()
    assert ddl.count("CREATE TABLE IF NOT EXISTS") == 7
    assert "__DATABASE__" in ddl
    assert "ledgerflow_dev." not in ddl

    redshift = (root / "infrastructure/sql/bootstrap_redshift.sql").read_text()
    assert "ledgerflow_dev" not in redshift
    assert "REPLACE_WITH_GLUE_DATABASE" in redshift
    assert "REPLACE_WITH_REDSHIFT_SPECTRUM_ROLE_ARN" in redshift

    athena = (root / "infrastructure/sql/athena_audit_queries.sql").read_text()
    assert "ledgerflow_dev" not in athena
    assert athena.count("__DATABASE__") == 3


def test_canonical_diagram_has_expected_dimensions_and_no_duplicate_copy() -> None:
    root = Path(__file__).resolve().parents[1]
    png = (root / "architecture/ledgerflow-payments-architecture.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (width, height) == (2048, 813)
    assert len(list((root / "architecture").glob("*.png"))) == 1
