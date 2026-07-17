from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from catalyst_data.database import connect
from catalyst_data.engine import build_record
from catalyst_data.repository import CatalystRepository
from catalyst_data.review import derive_quality, normalize_review_workflow, validate_review_workflow


def sample_record() -> dict:
    return build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))


def test_builder_adds_review_workflow_and_quality():
    record = sample_record()
    workflow = record["review_workflow"]
    assert workflow["schema_version"] == "catalyst-data-review-workflow/1.0"
    assert workflow["state"] == "draft"
    assert workflow["publication_gate"]["status"] == "blocked"
    assert workflow["quality"]["overall"] == round(sum(workflow["quality"][name] for name in ("completeness","validity","consistency","timeliness","provenance","uncertainty")) / 6)
    validate_review_workflow(workflow, record)


def test_review_workflow_persists_and_approval_is_snapshotted(tmp_path):
    repository = CatalystRepository(tmp_path / "review.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    record_id = record["record_id"]

    assert repository.assign_review(record_id, "reviewer@example.org", "coordinator@example.org") == "updated"
    assert repository.submit_review(record_id, "author@example.org", "Ready for review") == "updated"
    assert repository.start_review(record_id, "reviewer@example.org") == "updated"
    assert repository.decide_review(record_id, "approved", "reviewer@example.org", reason="Evidence and method are sufficient") == "updated"

    history = repository.review_history(record_id)
    assert history is not None
    assert history["workflow"]["state"] == "approved"
    assert history["workflow"]["publication_gate"]["status"] == "external"
    assert [item["decision_type"] for item in history["decisions"]][-4:] == ["assigned", "submitted", "review_started", "approved"]
    assert len(history["approval_snapshots"]) == 1
    assert repository.stats()["revision_diffs"] == 5
    assert len(repository.revision_history(record_id)) == 5


def test_comments_and_quality_assessments_are_append_only(tmp_path):
    repository = CatalystRepository(tmp_path / "quality.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    record_id = record["record_id"]
    repository.add_review_comment(record_id, "reviewer@example.org", "Clarify the verification boundary.")
    repository.assess_quality(record_id, "reviewer@example.org", {"validity": 91, "timeliness": 89}, basis={"validity":"Reviewed against observation flags."})
    history = repository.review_history(record_id)
    assert history and history["comments"][0]["body"].startswith("Clarify")
    assert history["quality_assessments"][-1]["validity"] == 91
    with connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="review comments are immutable"):
            connection.execute("UPDATE review_comments SET body='changed'")
        with pytest.raises(sqlite3.IntegrityError, match="quality assessments are immutable"):
            connection.execute("DELETE FROM quality_assessments")


def test_invalid_transition_is_rejected(tmp_path):
    repository = CatalystRepository(tmp_path / "transition.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    with pytest.raises(ValueError, match="not allowed"):
        repository.decide_review(record["record_id"], "approved", "reviewer@example.org")


def test_migration_six_populated_rollback_and_backfill(tmp_path):
    repository = CatalystRepository(tmp_path / "upgrade.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    assert repository.rollback(7) == [12, 11, 10, 9, 8, 7, 6]
    with connect(repository.path) as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM data_records WHERE record_id=?", (record["record_id"],)).fetchone()[0])
        payload.pop("review_workflow", None)
        connection.execute("UPDATE data_records SET payload_json=? WHERE record_id=?", (json.dumps(payload,sort_keys=True,separators=(",",":")),record["record_id"]))
        connection.commit()
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='review_cases'").fetchone() is None
    assert repository.migrate() == [6, 7, 8, 9, 10, 11, 12]
    stored = repository.get_record(record["record_id"])
    assert stored and stored["review_workflow"]["schema_version"] == "catalyst-data-review-workflow/1.0"
    assert repository.stats()["review_cases"] == 1
    assert repository.stats()["quality_assessments"] == 1


def test_quality_derivation_penalizes_stale_conflicting_records():
    record = sample_record()
    record["method"]["quality_flags"] = ["stale", "conflicting", "unverified"]
    quality = derive_quality(record)
    assert quality["timeliness"] == 45
    assert quality["consistency"] < 70
    assert quality["validity"] < 80
