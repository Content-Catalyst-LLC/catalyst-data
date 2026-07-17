from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.analysis_artifacts import AnalysisArtifactError, AnalysisArtifactService, normalize_analysis_definition
from catalyst_data.importer import ImportService
from catalyst_data.engine import percent_change
from catalyst_data.repository import CatalystRepository


def prepared_repository(tmp_path: Path) -> tuple[CatalystRepository, AnalysisArtifactService, list[str]]:
    repository = CatalystRepository(tmp_path / "analysis.sqlite3")
    assert repository.initialize() == list(range(1, 14))
    assert ImportService(repository).run(ROOT / "examples/imports/records.json").inserted == 2
    records = sorted(record["record_id"] for record in repository.list_records())
    service = AnalysisArtifactService(repository)
    definition = json.loads((ROOT / "examples/analyses/evidence_quality_analysis.json").read_text(encoding="utf-8"))
    definition["inputs"]["record_ids"] = records
    definition["inputs"]["roles"] = {records[1]: "comparison"}
    registered = service.register(definition, actor="principal:test")
    assert registered["artifact_id"] == "analysis:evidence-quality-summary"
    return repository, service, records


def test_analysis_contract_normalizes_and_rejects_unknown_fields():
    definition = json.loads((ROOT / "examples/analyses/evidence_quality_analysis.json").read_text(encoding="utf-8"))
    normalized = normalize_analysis_definition(definition)
    assert normalized["schema_version"] == "catalyst-data-analysis-artifact/1.0"
    assert normalized["environment"]["dependencies"] == ["catalyst-data==2.0.0"]
    invalid = deepcopy(definition)
    invalid["unexpected"] = True
    with pytest.raises(AnalysisArtifactError):
        normalize_analysis_definition(invalid)


def test_analysis_versions_are_immutable_and_activatable(tmp_path: Path):
    repository, service, records = prepared_repository(tmp_path)
    definition = json.loads((ROOT / "examples/analyses/evidence_quality_analysis.json").read_text(encoding="utf-8"))
    definition["inputs"]["record_ids"] = records
    definition["version"] = "1.1"
    definition["parameters"]["rounding_digits"] = 4
    result = service.register(definition, actor="principal:test")
    assert result["active_version"] == "1.1"
    versions = service.versions(definition["artifact_id"])
    assert [item["version"] for item in versions] == ["1.1", "1.0"]
    service.activate_version(definition["artifact_id"], "1.0", actor="principal:test")
    assert service.get(definition["artifact_id"])["active_version"] == "1.0"
    with sqlite3.connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE analysis_versions SET version='9.9' WHERE version='1.0'")


def test_run_freezes_inputs_and_outputs(tmp_path: Path):
    repository, service, records = prepared_repository(tmp_path)
    run = service.run("analysis:evidence-quality-summary", parameters={"rounding_digits": 3}, actor="principal:analyst")
    assert run["status"] == "completed"
    assert run["reproducibility_status"] == "reproducible"
    assert [item["record_id"] for item in run["inputs"]] == records
    assert run["outputs"][0]["name"] == "analysis-summary.json"
    assert repository.stats()["analysis_runs"] == 1
    assert repository.stats()["analysis_run_inputs"] == 2
    with sqlite3.connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE analysis_run_inputs SET role='reference'")


def test_packages_are_byte_identical_and_complete(tmp_path: Path):
    _, service, _ = prepared_repository(tmp_path)
    run = service.run("analysis:evidence-quality-summary")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    package_one = service.export_package(run["run_id"], first)
    package_two = service.export_package(run["run_id"], second)
    assert first.read_bytes() == second.read_bytes()
    assert package_one["package_sha256"] == package_two["package_sha256"]
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "SHA256SUMS", "README.md", "inputs/index.json", "outputs/index.json", "provenance/records.json", "review/records.json"}.issubset(names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == "catalyst-data-reproducible-package/1.0"
        assert manifest["run_id"] == run["run_id"]


def test_upstream_record_change_creates_invalidation_without_rewriting_frozen_input(tmp_path: Path):
    repository, service, records = prepared_repository(tmp_path)
    run = service.run("analysis:evidence-quality-summary")
    frozen = service.run_details(run["run_id"], include_payloads=True)["inputs"][0]
    changed = repository.get_record(records[0])
    assert changed is not None
    changed["measurement"]["current"] += 1
    changed["measurement"]["percent_change"] = percent_change(changed["measurement"].get("baseline"), changed["measurement"]["current"])
    changed["updated_at"] = "2026-07-17T20:00:00Z"
    repository.upsert_record(changed)
    details = service.run_details(run["run_id"], include_payloads=True)
    assert details["reproducibility_status"] == "invalidated"
    assert details["invalidations"][0]["reason"] == "upstream-record-changed"
    assert details["inputs"][0]["payload_sha256"] == frozen["payload_sha256"]
    assert details["inputs"][0]["payload"] == frozen["payload"]


def test_derived_lineage_and_replication_review_are_append_only(tmp_path: Path):
    repository, service, records = prepared_repository(tmp_path)
    run = service.run("analysis:evidence-quality-summary")
    lineage = service.add_derived_lineage(run["run_id"], records[0], [records[1]], transformation={"method": "comparison"}, actor="principal:analyst")
    assert lineage[0]["source_record_id"] == records[1]
    review = service.add_replication_review(run["run_id"], "confirmed", "reviewer@example.org", notes="Matched independently", evidence={"checksum_match": True})
    assert review["status"] == "confirmed"
    with sqlite3.connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM analysis_replication_reviews")


def test_populated_migration_011_rolls_back_and_reapplies(tmp_path: Path):
    repository, service, _ = prepared_repository(tmp_path)
    service.run("analysis:evidence-quality-summary")
    assert repository.rollback(3) == [13, 12, 11]
    assert repository.health().migration_version == 10
    assert repository.stats if True else None
    assert repository.migrate() == [11, 12, 13]
    assert repository.health().healthy
    assert repository.stats()["records"] == 2
    assert repository.stats()["analysis_artifacts"] == 0
