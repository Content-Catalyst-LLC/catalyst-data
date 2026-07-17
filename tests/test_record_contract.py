from copy import deepcopy
from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import RecordValidationError, build_record, schema, validate_record, validate_record_semantics


def canonical_record():
    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    return build_record(payload)


def test_canonical_schema_is_packaged_and_loadable():
    loaded = schema()
    assert loaded["$id"].endswith("catalyst-data-record-1.0.json")
    assert loaded["additionalProperties"] is False
    assert loaded["properties"]["extensions"]["additionalProperties"] is True


def test_sample_record_validates():
    validate_record(canonical_record())


def test_unknown_top_level_field_is_rejected():
    record = canonical_record()
    record["unexpected"] = True
    with pytest.raises(RecordValidationError, match="unexpected|Additional properties"):
        validate_record(record)


def test_unknown_nested_field_is_rejected():
    record = canonical_record()
    record["source"]["secret_note"] = "not namespaced"
    with pytest.raises(RecordValidationError, match="secret_note|Additional properties"):
        validate_record(record)


def test_invalid_extension_key_is_rejected():
    record = canonical_record()
    record["extensions"] = {"project": {"id": "x"}}
    with pytest.raises(RecordValidationError, match="project|does not match"):
        validate_record(record)


def test_namespaced_extension_is_accepted():
    record = canonical_record()
    record["extensions"]["org.example.analysis"] = {"score": 4}
    validate_record(record)


def test_invalid_source_url_is_rejected():
    record = canonical_record()
    record["source"]["url"] = "not a URL"
    with pytest.raises(RecordValidationError, match="url|uri"):
        validate_record(record)


def test_invalid_checksum_is_rejected():
    record = canonical_record()
    record["source"]["checksum"] = "sha256:abc"
    with pytest.raises(RecordValidationError, match="checksum|does not match"):
        validate_record(record)


def test_invalid_timestamp_order_is_rejected():
    record = canonical_record()
    record["updated_at"] = "2026-07-15T12:00:00Z"
    with pytest.raises(RecordValidationError, match="updated_at"):
        validate_record(record)


def test_invalid_period_order_is_rejected():
    record = canonical_record()
    record["period"]["end_date"] = "2026-03-01"
    with pytest.raises(RecordValidationError, match="period.end_date"):
        validate_record(record)


def test_semantic_percent_change_mismatch_is_rejected():
    record = canonical_record()
    record["measurement"]["percent_change"] = 900
    with pytest.raises(RecordValidationError, match="percent_change"):
        validate_record_semantics(record)


def test_semantic_review_mismatch_is_rejected():
    record = canonical_record()
    record["review"]["status"] = "needs evidence"
    with pytest.raises(RecordValidationError, match="review.status"):
        validate_record_semantics(record)


def test_semantic_signal_mismatch_is_rejected():
    record = canonical_record()
    record["review"]["signal_status"] = "declining"
    with pytest.raises(RecordValidationError, match="signal_status"):
        validate_record_semantics(record)


def test_duplicate_quality_flags_are_rejected():
    record = canonical_record()
    record["method"]["quality_flags"] = ["estimated", "estimated"]
    with pytest.raises(RecordValidationError, match="quality_flags|non-unique"):
        validate_record(record)


def test_invalid_quality_flag_is_rejected():
    record = canonical_record()
    record["method"]["quality_flags"] = ["mystery"]
    with pytest.raises(RecordValidationError, match="mystery|quality_flags"):
        validate_record(record)


def test_indicator_governance_is_part_of_canonical_record():
    record = canonical_record()
    governance = record["indicator_governance"]
    assert governance["schema_version"] == "catalyst-data-indicator-governance/1.0"
    assert governance["unit"]["symbol"] == record["indicator"]["unit"]
    validate_record(record)
    validate_record_semantics(record)


def test_indicator_governance_unit_mismatch_is_rejected_semantically():
    record = canonical_record()
    record["indicator_governance"]["unit"]["symbol"] = "different"
    with pytest.raises(RecordValidationError, match="unit.symbol"):
        validate_record_semantics(record)


def test_approved_methodology_without_approval_metadata_is_rejected_semantically():
    record = canonical_record()
    record["indicator_governance"]["methodology"]["status"] = "approved"
    record["indicator_governance"]["methodology"]["approved_by"] = None
    record["indicator_governance"]["methodology"]["approved_at"] = None
    with pytest.raises(RecordValidationError, match="approved methodology"):
        validate_record_semantics(record)


def test_indicator_version_must_be_declared_comparable():
    record = canonical_record()
    record["indicator_governance"]["compatibility"]["comparable_versions"] = ["9.9"]
    with pytest.raises(RecordValidationError, match="indicator version"):
        validate_record_semantics(record)
