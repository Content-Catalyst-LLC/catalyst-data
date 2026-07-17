#!/usr/bin/env python3
"""Portable release smoke tests for installer environments."""
from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import (
    RecordValidationError,
    build_record,
    classify_review,
    classify_signal,
    convert_legacy_record,
    CatalystRepository,
    ImportService,
    percent_change,
    validate_record,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    check(percent_change(100, 125) == 25.0, "positive percent change failed")
    check(percent_change(0, 50) is None, "zero baseline must be indeterminate")
    check(percent_change(None, 50) is None, "missing baseline must be indeterminate")
    check(classify_review(90, "") == "missing source", "missing source precedence failed")
    check(classify_review(68, "Source") == "reviewable with caution", "caution threshold failed")
    check(classify_signal(-10, "lower") == "improving", "lower-is-better signal failed")

    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    record = build_record(payload)
    validate_record(record)
    check(record["schema_version"] == "catalyst-data-record/1.0", "record contract failed")
    check(record["producer"]["version"] == "1.8.0", "producer version failed")
    check(record["review"]["status"] == "reviewable", "sample review status failed")
    check(record["review"]["signal_status"] == "improving", "sample signal status failed")
    check(record["source"]["publisher"] == "Content Catalyst LLC", "source provenance failed")
    check(record["evidence_chain"]["schema_version"] == "catalyst-data-evidence-chain/1.0", "evidence contract failed")
    check(len(record["evidence_chain"]["sources"]) == 2, "multi-source evidence failed")
    check(record["evidence_chain"]["completeness_score"] == 100, "evidence completeness failed")
    governance = record["indicator_governance"]
    check(governance["schema_version"] == "catalyst-data-indicator-governance/1.0", "indicator governance contract failed")
    check(governance["status"] == "active", "indicator status failed")
    check(governance["unit"]["symbol"] == record["indicator"]["unit"], "governed unit failed")
    check(governance["methodology"]["version"] == record["indicator"]["version"], "methodology version failed")
    workflow = record["review_workflow"]
    check(workflow["schema_version"] == "catalyst-data-review-workflow/1.0", "review workflow contract failed")
    check(workflow["state"] == "draft", "default review state failed")
    check(0 <= workflow["quality"]["overall"] <= 100, "quality assessment failed")

    invalid = deepcopy(record)
    invalid["unexpected"] = True
    try:
        validate_record(invalid)
    except RecordValidationError:
        pass
    else:
        raise RuntimeError("unknown canonical fields must be rejected")

    legacy = json.loads((ROOT / "examples/sample_legacy_v1_0_record.json").read_text(encoding="utf-8"))
    upgraded = convert_legacy_record(
        legacy,
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    validate_record(upgraded)
    check(upgraded["producer"]["component"] == "migration-tool", "legacy producer failed")
    check(upgraded["measurement"]["percent_change"] == 25.0, "legacy derived value failed")


    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        repository = CatalystRepository(Path(directory) / "catalyst-data.sqlite3")
        applied = repository.initialize()
        check(applied == [1, 2, 3, 4, 5, 6, 7, 8], "repository migrations failed")
        dry_run = ImportService(repository).run(ROOT / "examples/imports/records.json", dry_run=True)
        check(dry_run.inserted == 2 and dry_run.rolled_back, "repository dry run failed")
        check(repository.stats()["records"] == 0, "dry run persisted records")
        imported = ImportService(repository).run(ROOT / "examples/imports/records.json")
        check(imported.inserted == 2, "repository import failed")
        repeated = ImportService(repository).run(ROOT / "examples/imports/records.json")
        check(repeated.skipped == 2, "repository idempotence failed")
        check(repository.health().healthy, "repository health failed")
        stats = repository.stats()
        check(stats["source_versions"] >= 2, "source version history failed")
        check(stats["record_revisions"] == 2, "record revision history failed")
        check(stats["indicator_versions"] >= 2, "indicator version history failed")
        check(stats["methodology_versions"] >= 2, "methodology version history failed")
        stored = repository.list_records(limit=1)[0]
        record_id = stored["record_id"]
        check(repository.evidence(record_id) is not None, "evidence inspection failed")
        check(repository.indicator_registry(stored["indicator"]["id"]), "indicator registry failed")
        unit_id = stored["indicator_governance"]["unit"]["id"]
        check(repository.convert(5, unit_id, unit_id) == 5, "unit conversion failed")
        check(repository.compare(record_id, record_id)["status"] == "equivalent", "comparability failed")
        check(stats["review_cases"] == 2 and stats["quality_assessments"] == 2, "review persistence failed")
        repository.assign_review(record_id, "reviewer@example.org", "author@example.org")
        repository.submit_review(record_id, "author@example.org", "Ready")
        repository.start_review(record_id, "reviewer@example.org")
        repository.decide_review(record_id, "approved", "reviewer@example.org", reason="Approved")
        check(bool(repository.review_history(record_id)["approval_snapshots"]), "approval snapshot failed")
        from catalyst_data.query_studio import QueryStudio
        studio = QueryStudio(repository)
        saved = studio.save({"name":"Smoke query","filters":{},"sort":[],"limit":100}, actor="smoke")
        run = studio.run(saved["query_id"])
        check(run["summary"]["record_count"] == 2, "query studio failed")
        bundle = Path(directory) / "smoke-bundle.zip"
        studio.export_bundle(run["run_id"], bundle)
        check(bundle.exists(), "query bundle failed")
        from catalyst_data.public_api import ApiRegistry, public_projection, openapi_document
        from catalyst_data.handoff import create_handoff, validate_handoff
        key = ApiRegistry(repository).create_key("smoke", ["records:write", "handoffs:write"])
        check(key["token"].startswith("cd_"), "API key creation failed")
        handoff = create_handoff([stored], target_product="decision-studio", target_capability="decision-evidence", source_version="1.8.0")
        validate_handoff(handoff)
        receipt = ApiRegistry(repository).receive_handoff(handoff)
        check(receipt["status"] == "accepted", "handoff receipt failed")
        check(openapi_document()["openapi"] == "3.1.0", "OpenAPI generation failed")

    database = sqlite3.connect(":memory:")
    database.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    database.executescript((ROOT / "queries.sql").read_text(encoding="utf-8"))
    count = database.execute("SELECT COUNT(*) FROM measurement_review").fetchone()[0]
    check(count == 2, f"expected 2 seeded measurements, found {count}")
    database.close()
    print("Portable release smoke tests passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
