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
from catalyst_data.governance import compare_governance, convert_value, normalize_indicator_governance
from catalyst_data.repository import CatalystRepository


def sample_record():
    return build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))


def test_default_governance_is_added_to_canonical_record():
    record = sample_record()
    governance = record["indicator_governance"]
    assert governance["schema_version"] == "catalyst-data-indicator-governance/1.0"
    assert governance["status"] == "active"
    assert governance["unit"]["symbol"] == record["indicator"]["unit"]
    assert record["indicator"]["version"] in governance["compatibility"]["comparable_versions"]


def test_approved_methodology_requires_approval_metadata():
    record = sample_record()
    raw = deepcopy(record["indicator_governance"])
    raw["methodology"]["status"] = "approved"
    raw["methodology"]["approved_by"] = None
    raw["methodology"]["approved_at"] = None
    with pytest.raises(ValueError, match="approved_by"):
        normalize_indicator_governance(record["indicator"], record["method"], raw)


def test_unit_conversion_uses_canonical_basis():
    kwh = {"id":"unit:kwh","symbol":"kWh","name":"kilowatt-hour","dimension":"energy","canonical_unit_id":"unit:kwh","conversion_factor":1.0,"conversion_offset":0.0}
    mwh = {"id":"unit:mwh","symbol":"MWh","name":"megawatt-hour","dimension":"energy","canonical_unit_id":"unit:kwh","conversion_factor":1000.0,"conversion_offset":0.0}
    assert convert_value(2, mwh, kwh) == 2000
    assert convert_value(500, kwh, mwh) == 0.5


def test_unit_conversion_rejects_incompatible_dimensions():
    energy = {"id":"unit:kwh","symbol":"kWh","name":"kilowatt-hour","dimension":"energy","canonical_unit_id":"unit:kwh","conversion_factor":1.0,"conversion_offset":0.0}
    mass = {"id":"unit:kg","symbol":"kg","name":"kilogram","dimension":"mass","canonical_unit_id":"unit:kg","conversion_factor":1.0,"conversion_offset":0.0}
    with pytest.raises(ValueError, match="incompatible dimensions"):
        convert_value(1, energy, mass)


def governed_pair():
    left = sample_record()
    right = deepcopy(left)
    right["record_id"] = "measurement:comparison:right"
    right["period"] = {"id":"period:2026-q3","label":"2026-Q3","start_date":"2026-07-01","end_date":"2026-09-30"}
    right["source"] = deepcopy(left["source"])
    previous_source_id = right["source"]["id"]
    right["source"]["id"] = "source:comparison:right"
    right["source"]["name"] = "Comparison source"
    right["evidence_chain"]["sources"][0]["source"] = deepcopy(right["source"])
    for relationship in right["evidence_chain"]["relationships"]:
        if relationship["subject_source_id"] == previous_source_id:
            relationship["subject_source_id"] = right["source"]["id"]
        if relationship["object_source_id"] == previous_source_id:
            relationship["object_source_id"] = right["source"]["id"]
    return left, right


def test_comparability_reports_equivalent_for_same_governance():
    left, right = governed_pair()
    result = compare_governance(left, right)
    assert result["status"] == "equivalent"
    assert result["conversion_available"] is True


def test_comparability_reports_convertible_for_compatible_units():
    left, right = governed_pair()
    right["indicator"]["unit"] = "Mscore"
    right["indicator_governance"]["unit"] = {
        "id":"unit:mscore","symbol":"Mscore","name":"million score","dimension":"score",
        "canonical_unit_id":left["indicator_governance"]["unit"]["canonical_unit_id"],
        "conversion_factor":1000000.0,"conversion_offset":0.0,
    }
    result = compare_governance(left, right)
    assert result["status"] == "convertible"


def test_comparability_reports_limited_for_frequency_mismatch():
    left, right = governed_pair()
    right["indicator_governance"]["frequency"] = "quarterly"
    result = compare_governance(left, right)
    assert result["status"] == "limited"
    assert "frequencies differ" in " ".join(result["reasons"])


def test_comparability_reports_incompatible_for_direction_mismatch():
    left, right = governed_pair()
    right["indicator"]["direction"] = "lower"
    result = compare_governance(left, right)
    assert result["status"] == "incompatible"


def test_repository_persists_governed_registry_and_history(tmp_path):
    repository = CatalystRepository(tmp_path / "governance.sqlite3")
    repository.initialize()
    record = sample_record()
    assert repository.upsert_record(record) == "inserted"
    stats = repository.stats()
    assert stats["indicator_versions"] == 1
    assert stats["methodology_versions"] == 1
    assert stats["units"] == 1
    assert stats["governance_events"] >= 3
    registry = repository.indicator_registry(record["indicator"]["id"])
    assert registry[0]["status"] == "active"
    methods = repository.methodology_history(record["indicator_governance"]["methodology"]["id"])
    assert methods[0]["payload"]["title"].endswith("methodology")
    units = repository.unit_registry(record["indicator_governance"]["unit"]["id"])
    assert units[0]["symbol"] == record["indicator"]["unit"]


def test_indicator_and_methodology_versions_are_immutable(tmp_path):
    repository = CatalystRepository(tmp_path / "immutable.sqlite3")
    repository.initialize(); repository.upsert_record(sample_record())
    with connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="indicator_versions are immutable"):
            connection.execute("UPDATE indicator_versions SET status='archived'")
        with pytest.raises(sqlite3.IntegrityError, match="methodology_versions are immutable"):
            connection.execute("DELETE FROM methodology_versions")


def test_governance_change_creates_new_indicator_and_methodology_versions(tmp_path):
    repository = CatalystRepository(tmp_path / "versions.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    changed = deepcopy(record)
    changed["updated_at"] = "2026-07-16T13:00:00Z"
    changed["indicator"]["version"] = "1.1"
    changed["indicator_governance"]["compatibility"]["comparable_versions"] = ["1.0", "1.1"]
    changed["indicator_governance"]["methodology"]["version"] = "1.1"
    changed["indicator_governance"]["methodology"]["revision_notes"] = "Clarified denominator treatment."
    assert repository.upsert_record(changed) == "updated"
    stats = repository.stats()
    assert stats["indicator_versions"] == 2
    assert stats["methodology_versions"] == 2


def test_repository_compare_and_convert(tmp_path):
    repository = CatalystRepository(tmp_path / "compare.sqlite3")
    repository.initialize(); left, right = governed_pair()
    repository.upsert_record(left); repository.upsert_record(right)
    result = repository.compare(left["record_id"], right["record_id"])
    assert result["status"] == "equivalent"
    unit_id = left["indicator_governance"]["unit"]["id"]
    assert repository.convert(12, unit_id, unit_id) == 12


def test_migration_four_backfills_v13_record(tmp_path):
    repository = CatalystRepository(tmp_path / "upgrade.sqlite3")
    repository.initialize(); record = sample_record(); repository.upsert_record(record)
    assert repository.rollback(10) == [13, 12, 11, 10, 9, 8, 7, 6, 5, 4]
    with connect(repository.path) as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM data_records WHERE record_id=?", (record["record_id"],)).fetchone()[0])
        payload.pop("indicator_governance", None)
        connection.execute("UPDATE data_records SET payload_json=? WHERE record_id=?", (json.dumps(payload, sort_keys=True, separators=(",", ":")), record["record_id"]))
        connection.commit()
    assert repository.migrate() == [4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    stored = repository.get_record(record["record_id"])
    assert stored and stored["indicator_governance"]["schema_version"] == "catalyst-data-indicator-governance/1.0"
    assert repository.stats()["indicator_versions"] == 1
