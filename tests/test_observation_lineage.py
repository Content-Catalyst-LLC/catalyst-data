from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import build_record
from catalyst_data.database import connect
from catalyst_data.lineage import lineage_completeness, normalize_observation_lineage, validate_observation_lineage
from catalyst_data.repository import CatalystRepository
from catalyst_data.validation import RecordValidationError


def sample_record():
    return build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))


def test_default_lineage_is_added_to_canonical_record():
    record = sample_record()
    lineage = record["observation_lineage"]
    assert lineage["schema_version"] == "catalyst-data-observation-lineage/1.0"
    assert lineage["completeness_score"] == 100
    assert len(lineage["questions"]) == 1
    assert len(lineage["instruments"]) == 1
    assert len(lineage["datasets"]) == 1
    assert len(lineage["batches"]) == 1
    assert {item["role"] for item in lineage["observations"]} == {"baseline", "current"}
    assert lineage["transformations"][0]["input_observation_ids"] == [item["id"] for item in lineage["observations"]]


def test_zero_or_missing_baseline_emits_only_current_observation():
    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    payload["values"]["baseline"] = None
    record = build_record(payload)
    assert [item["role"] for item in record["observation_lineage"]["observations"]] == ["current"]
    assert record["observation_lineage"]["batches"][0]["record_count"] == 1


def test_lineage_rejects_unknown_batch_reference():
    record = sample_record()
    lineage = deepcopy(record["observation_lineage"])
    lineage["observations"][0]["batch_id"] = "batch:unknown:123"
    with pytest.raises(ValueError, match="unknown batch"):
        validate_observation_lineage(lineage, record)


def test_lineage_rejects_transformation_unknown_observation():
    record = sample_record()
    lineage = deepcopy(record["observation_lineage"])
    lineage["transformations"][0]["input_observation_ids"].append("observation:unknown:123")
    with pytest.raises(ValueError, match="unknown observations"):
        validate_observation_lineage(lineage, record)


def test_lineage_rejects_current_observation_value_mismatch():
    record = sample_record()
    lineage = deepcopy(record["observation_lineage"])
    next(item for item in lineage["observations"] if item["role"] == "current")["value"] += 1
    with pytest.raises(ValueError, match="measurement.current"):
        validate_observation_lineage(lineage, record)


def test_lineage_completeness_is_deterministic():
    record = sample_record()
    lineage = deepcopy(record["observation_lineage"])
    assert lineage_completeness(lineage) == 100
    lineage["transformations"] = []
    assert lineage_completeness(lineage) == 85


def test_repository_persists_question_to_observation_chain(tmp_path):
    repository = CatalystRepository(tmp_path / "lineage.sqlite3")
    repository.initialize()
    record = sample_record()
    assert repository.upsert_record(record) == "inserted"
    stats = repository.stats()
    assert stats["questions"] == 1
    assert stats["instruments"] == 1
    assert stats["instrument_versions"] == 1
    assert stats["datasets"] == 1
    assert stats["dataset_versions"] == 1
    assert stats["observation_batches"] == 1
    assert stats["observations"] == 2
    assert stats["observation_transformations"] == 1
    assert stats["lineage_events"] >= 7
    payload = repository.lineage(record["record_id"])
    assert payload is not None
    assert payload["summary"]["question_count"] == 1
    assert payload["summary"]["observation_count"] == 2
    assert payload["summary"]["transformation_count"] == 1


def test_instrument_dataset_and_lineage_history_are_immutable(tmp_path):
    repository = CatalystRepository(tmp_path / "immutable-lineage.sqlite3")
    repository.initialize(); repository.upsert_record(sample_record())
    with connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="instrument versions are immutable"):
            connection.execute("UPDATE instrument_versions SET version='9.9'")
        with pytest.raises(sqlite3.IntegrityError, match="dataset versions are immutable"):
            connection.execute("DELETE FROM dataset_versions")
        with pytest.raises(sqlite3.IntegrityError, match="lineage events are immutable"):
            connection.execute("UPDATE lineage_events SET actor='tampered'")


def test_changed_instrument_and_dataset_create_new_versions(tmp_path):
    repository = CatalystRepository(tmp_path / "versions.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    changed = deepcopy(record)
    changed["updated_at"] = "2026-07-16T14:00:00Z"
    changed["observation_lineage"]["instruments"][0]["version"] = "1.1"
    changed["observation_lineage"]["instruments"][0]["protocol"] = "Revised collection protocol."
    changed["observation_lineage"]["datasets"][0]["version"] = "2.0"
    changed["observation_lineage"]["datasets"][0]["description"] = "Revised dataset release."
    assert repository.upsert_record(changed) == "updated"
    stats = repository.stats()
    assert stats["instrument_versions"] == 2
    assert stats["dataset_versions"] == 2


def test_repository_resynchronizes_observation_values_on_measurement_update(tmp_path):
    repository = CatalystRepository(tmp_path / "sync.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    changed = deepcopy(record)
    changed["updated_at"] = "2026-07-16T14:00:00Z"
    changed["measurement"]["current"] = 80.0
    changed["measurement"]["percent_change"] = round(((80.0 - changed["measurement"]["baseline"]) / abs(changed["measurement"]["baseline"])) * 100, 2)
    changed["review"]["signal_status"] = "improving"
    assert repository.upsert_record(changed) == "updated"
    observations = repository.observations(record["record_id"])
    current = next(item for item in observations if item["role"] == "current")
    assert current["value"] == 80.0


def test_migration_five_backfills_v14_record(tmp_path):
    repository = CatalystRepository(tmp_path / "upgrade.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    assert repository.rollback(9) == [13, 12, 11, 10, 9, 8, 7, 6, 5]
    with connect(repository.path) as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM data_records WHERE record_id=?", (record["record_id"],)).fetchone()[0])
        payload.pop("observation_lineage", None)
        connection.execute("UPDATE data_records SET payload_json=? WHERE record_id=?", (json.dumps(payload, sort_keys=True, separators=(",", ":")), record["record_id"]))
        connection.commit()
    assert repository.migrate() == [5, 6, 7, 8, 9, 10, 11, 12, 13]
    stored = repository.get_record(record["record_id"])
    assert stored and stored["observation_lineage"]["schema_version"] == "catalyst-data-observation-lineage/1.0"
    assert repository.stats()["observations"] == 2


def test_populated_migration_five_rolls_back_and_reapplies(tmp_path):
    repository = CatalystRepository(tmp_path / "rollback.sqlite3")
    repository.initialize(); repository.upsert_record(sample_record())
    assert repository.rollback(9) == [13, 12, 11, 10, 9, 8, 7, 6, 5]
    with connect(repository.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='observations'").fetchone() is None
        assert connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0] == 1
    assert repository.migrate() == [5, 6, 7, 8, 9, 10, 11, 12, 13]
    assert repository.stats()["observations"] == 2


def test_repository_query_apis(tmp_path):
    repository = CatalystRepository(tmp_path / "queries.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    lineage = record["observation_lineage"]
    assert repository.questions(lineage["questions"][0]["id"])[0]["status"] == "active"
    assert repository.instruments(lineage["instruments"][0]["id"])[0]["current_version"] == "1.0"
    assert repository.datasets(lineage["datasets"][0]["id"])[0]["access_classification"] == "public"
    assert len(repository.observations(record["record_id"], quality_status="valid")) == 2
