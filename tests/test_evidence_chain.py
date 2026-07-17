from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import build_record, percent_change, classify_signal
from catalyst_data.repository import CatalystRepository
from catalyst_data.validation import RecordValidationError, validate_record
from catalyst_data.engine import validate_record_semantics


def sample_record():
    return build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))


def test_sample_contains_multi_source_evidence_chain():
    record = sample_record()
    chain = record["evidence_chain"]
    assert chain["schema_version"] == "catalyst-data-evidence-chain/1.0"
    assert len(chain["sources"]) == 2
    assert [item["role"] for item in chain["sources"]] == ["primary", "supporting"]
    assert chain["relationships"][0]["predicate"] == "corroborates"
    assert chain["transformations"][0]["operation"] == "weighted aggregation"
    assert chain["completeness_score"] == 100
    assert chain["gaps"] == []


def test_invalid_evidence_role_is_rejected():
    record = sample_record()
    record["evidence_chain"]["sources"][1]["role"] = "mystery"
    with pytest.raises(RecordValidationError, match="role|mystery"):
        validate_record(record)


def test_inconsistent_primary_source_metadata_is_rejected():
    record = sample_record()
    record["source"]["citation"] = "Changed citation"
    with pytest.raises(RecordValidationError, match="primary source metadata"):
        validate_record_semantics(record)


def test_incorrect_completeness_score_is_rejected():
    record = sample_record()
    record["evidence_chain"]["completeness_score"] = 4
    with pytest.raises(RecordValidationError, match="completeness_score"):
        validate_record_semantics(record)


def test_repository_persists_sources_relationships_revisions_and_provenance(tmp_path):
    repository = CatalystRepository(tmp_path / "evidence.sqlite3")
    repository.initialize()
    record = sample_record()
    assert repository.upsert_record(record) == "inserted"
    stats = repository.stats()
    assert stats["sources"] == 2
    assert stats["source_versions"] == 2
    assert stats["source_snapshots"] == 2
    assert stats["evidence_links"] == 2
    assert stats["record_revisions"] == 1
    assert stats["provenance_events"] >= 6
    assert stats["open_evidence_gaps"] == 0
    evidence = repository.evidence(record["record_id"])
    assert evidence is not None
    assert evidence["summary"]["source_count"] == 2
    assert evidence["summary"]["supporting_source_count"] == 1
    assert evidence["summary"]["revision_count"] == 1
    assert any(item["event_type"] == "transformed" for item in evidence["provenance"])
    with sqlite3.connect(repository.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM source_relationships WHERE predicate='corroborates'").fetchone()[0]
        assert count == 1


def test_changed_source_creates_new_source_version_and_record_revision(tmp_path):
    repository = CatalystRepository(tmp_path / "evidence.sqlite3")
    repository.initialize()
    record = sample_record()
    repository.upsert_record(record)
    changed = deepcopy(record)
    changed["updated_at"] = "2026-07-16T13:00:00Z"
    changed["source"]["citation"] = "Updated primary citation."
    changed["evidence_chain"]["sources"][0]["source"]["citation"] = "Updated primary citation."
    assert repository.upsert_record(changed) == "updated"
    history = repository.source_history(record["source"]["id"])
    assert [item["version_number"] for item in history] == [2, 1]
    evidence = repository.evidence(record["record_id"])
    assert evidence is not None
    assert [item["revision_number"] for item in evidence["revisions"]] == [1, 2]
    assert evidence["summary"]["revision_count"] == 2
    assert any(item["event_type"] == "record_updated" for item in evidence["provenance"])


def test_immutable_history_tables_reject_update_and_delete(tmp_path):
    repository = CatalystRepository(tmp_path / "evidence.sqlite3")
    repository.initialize()
    repository.upsert_record(sample_record())
    with sqlite3.connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE source_versions SET version_number=99 WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM record_revisions WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE provenance_events SET actor='x' WHERE id=1")


def test_evidence_gaps_are_derived_and_persisted(tmp_path):
    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    payload.pop("evidence_chain", None)
    payload["source"] = {"name": "Incomplete source", "type": "other"}
    payload["confidence"] = {"score": 20, "basis": "Unverified"}
    payload["method"]["notes"] = ""
    record = build_record(payload)
    codes = {item["code"] for item in record["evidence_chain"]["gaps"]}
    assert {"missing-citation", "missing-license", "missing-retrieval-date", "missing-checksum", "missing-method", "low-confidence"}.issubset(codes)
    repository = CatalystRepository(tmp_path / "gaps.sqlite3")
    repository.initialize(); repository.upsert_record(record)
    evidence = repository.evidence(record["record_id"])
    assert evidence is not None
    persisted = {item["gap_code"] for item in evidence["open_gaps"]}
    assert codes == persisted


def test_manual_snapshot_is_append_only_and_emits_provenance(tmp_path):
    repository = CatalystRepository(tmp_path / "snapshot.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    snapshot_id = repository.add_source_snapshot(
        record["source"]["id"],
        retrieved_at="2026-07-17T09:00:00Z",
        content_sha256="sha256:" + "3" * 64,
        storage_uri="file:///tmp/source-snapshot.json",
        media_type="application/json",
        byte_size=1024,
        metadata={"capture": "manual validation"},
    )
    assert snapshot_id.startswith("snapshot:")
    assert repository.stats()["source_snapshots"] == 3
    assert any(item["event_type"] == "source_snapshot_added" for item in repository.provenance(record["record_id"]))
