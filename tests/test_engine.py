from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import (
    build_record,
    classify_record,
    classify_review,
    classify_signal,
    convert_legacy_record,
    percent_change,
    stable_id,
)


def sample_payload():
    return json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))


def test_percent_change():
    assert percent_change(100, 125) == 25.0
    assert percent_change(100, 80) == -20.0
    assert percent_change(-100, -80) == 20.0
    assert percent_change(0, 50) is None
    assert percent_change(None, 50) is None


def test_review_classification_is_evidence_readiness_only():
    assert classify_review(72, "Named source") == "reviewable"
    assert classify_review(68, "Named source") == "reviewable with caution"
    assert classify_review(30, "Named source") == "needs evidence"
    assert classify_review(90, "") == "missing source"
    assert classify_record(72, 12, "higher") == "reviewable"


def test_signal_classification_is_separate():
    assert classify_signal(12, "higher") == "improving"
    assert classify_signal(-12, "higher") == "declining"
    assert classify_signal(-12, "lower") == "improving"
    assert classify_signal(0, "lower") == "unchanged"
    assert classify_signal(12, "neutral") == "descriptive"
    assert classify_signal(None, "higher") == "indeterminate"


def test_build_record_from_sample_is_canonical():
    record = build_record(sample_payload())
    assert record["$schema"].endswith("catalyst-data-record-1.0.json")
    assert record["schema_version"] == "catalyst-data-record/1.0"
    assert record["record_type"] == "measurement"
    assert record["entity"]["name"] == "Urban Tree Canopy Program"
    assert record["measurement"]["percent_change"] == 25.81
    assert record["review"]["status"] == "reviewable"
    assert record["review"]["signal_status"] == "improving"
    assert record["source"]["publisher"] == "Content Catalyst LLC"
    assert record["method"]["quality_flags"] == ["unverified"]


def test_build_record_ids_are_stable():
    first = build_record(sample_payload())
    second = build_record(sample_payload())
    assert first["record_id"] == second["record_id"]
    assert first["entity"]["id"] == second["entity"]["id"]
    assert first["source"]["id"] == second["source"]["id"]
    assert stable_id("period", "2026-Q2") == stable_id("period", "2026-Q2")


def test_build_record_zero_baseline_and_missing_source():
    payload = sample_payload()
    payload["values"]["baseline"] = 0
    payload["source"]["name"] = ""
    payload["confidence"] = {"score": 95, "basis": "High confidence in the measurement, but no source supplied."}
    record = build_record(payload)
    assert record["measurement"]["percent_change"] is None
    assert record["source"]["name"] == "Unspecified source"
    assert record["review"]["status"] == "missing source"
    assert record["review"]["signal_status"] == "indeterminate"


@pytest.mark.parametrize("confidence", [-1, 101, float("inf")])
def test_invalid_confidence_is_rejected(confidence):
    payload = sample_payload()
    payload["confidence"] = confidence
    with pytest.raises(ValueError, match="confidence"):
        build_record(payload)


def test_invalid_direction_is_rejected():
    payload = sample_payload()
    payload["indicator"]["direction"] = "sideways"
    with pytest.raises(ValueError, match="direction"):
        build_record(payload)


def test_legacy_converter_recalculates_untrusted_derived_fields():
    legacy = json.loads((ROOT / "examples/sample_legacy_v1_0_record.json").read_text(encoding="utf-8"))
    legacy["values"]["percent_change"] = 999
    legacy["review_status"] = "reviewable"
    record = convert_legacy_record(
        legacy,
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    assert record["measurement"]["percent_change"] == 25.0
    assert record["review"]["status"] == "reviewable with caution"
    assert record["producer"]["component"] == "migration-tool"


def test_canonical_record_is_returned_without_rewriting():
    original = build_record(sample_payload())
    record = build_record(deepcopy(original))
    assert record == original
