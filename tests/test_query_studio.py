from __future__ import annotations

import json
import sqlite3
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from catalyst_data import CatalystRepository, build_record
from catalyst_data.query_studio import QueryStudio, apply_query, normalize_query_definition

ROOT = Path(__file__).resolve().parents[1]


def two_period_records():
    base = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    first = deepcopy(base)
    first["period"] = {"label": "2025", "type": "year", "start_date": "2025-01-01", "end_date": "2025-12-31"}
    first["values"]["current"] = 60
    second = deepcopy(base)
    second["period"] = {"label": "2026", "type": "year", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    second["values"]["current"] = 75
    return build_record(first), build_record(second)


def test_query_normalization_rejects_unknown_filters():
    with pytest.raises(ValueError, match="unsupported query filters"):
        normalize_query_definition({"name": "Bad", "filters": {"unknown": True}})


def test_saved_query_versions_runs_and_frozen_records(tmp_path):
    repository = CatalystRepository(tmp_path / "query.db")
    repository.initialize()
    first, second = two_period_records()
    repository.upsert_record(first)
    repository.upsert_record(second)
    studio = QueryStudio(repository)
    saved = studio.save({"name": "Canopy trend", "filters": {"entity_ids": [first["entity"]["id"]]}, "limit": 100}, actor="analyst")
    changed = studio.save({"name": "Canopy trend", "filters": {"entity_ids": [first["entity"]["id"]], "quality_min": 0}, "limit": 100}, actor="analyst")
    assert changed["version_count"] == 2
    run = studio.run(saved["query_id"])
    assert run["summary"]["record_count"] == 2
    assert len(run["comparisons"]) == 1
    assert run["comparisons"][0]["percent_change"] == 25.0
    frozen = studio.get_run(run["run_id"])
    modified = deepcopy(second)
    modified["review"]["reviewer_notes"] = "Updated after the frozen query run."
    modified["updated_at"] = "2026-07-17T18:00:00Z"
    repository.upsert_record(modified)
    assert studio.get_run(run["run_id"])["records"] == frozen["records"]
    assert repository.stats()["saved_query_versions"] == 2
    assert repository.stats()["query_run_records"] == 2


def test_query_filters_and_reproducible_export_bundle(tmp_path):
    repository = CatalystRepository(tmp_path / "bundle.db")
    repository.initialize()
    first, second = two_period_records()
    repository.upsert_record(first); repository.upsert_record(second)
    studio = QueryStudio(repository)
    run = studio.run({"name": "2026 only", "filters": {"period_labels": ["2026"]}, "limit": 10})
    assert [item["period"]["label"] for item in run["records"]] == ["2026"]
    bundle = tmp_path / "bundle.zip"
    result = studio.export_bundle(run["run_id"], bundle)
    original = bundle.read_bytes()
    studio.export_bundle(run["run_id"], bundle)
    assert bundle.read_bytes() == original
    assert result["manifest_sha256"]
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "records.json", "records.csv", "brief.md", "comparisons.json", "warnings.json", "provenance.json", "review.json", "data-dictionary.json"} <= names


def test_query_history_is_immutable(tmp_path):
    repository = CatalystRepository(tmp_path / "immutable.db")
    repository.initialize()
    record, _ = two_period_records(); repository.upsert_record(record)
    studio = QueryStudio(repository)
    saved = studio.save({"name": "Immutable", "filters": {}, "limit": 10})
    run = studio.run(saved["query_id"])
    connection = sqlite3.connect(repository.path)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE query_runs SET record_count=99 WHERE run_id=?", (run["run_id"],))
    connection.close()


def test_migration_007_populated_rollback_and_reapply(tmp_path):
    repository = CatalystRepository(tmp_path / "rollback.db")
    repository.initialize()
    record, _ = two_period_records(); repository.upsert_record(record)
    studio = QueryStudio(repository); saved = studio.save({"name": "Rollback", "filters": {}, "limit": 10}); studio.run(saved["query_id"])
    assert repository.rollback(5) == [11, 10, 9, 8, 7]
    assert repository.migrate() == [7, 8, 9, 10, 11]
    assert repository.stats()["saved_queries"] == 0
