from __future__ import annotations

import json
import math
import re
from datetime import datetime
from importlib import resources
from typing import Any, Mapping

from ._record_contract import (
    EXTENSION_KEY_PATTERN,
    ID_PATTERN,
    PRODUCER_COMPONENTS,
    QUALITY_FLAGS,
    RECORD_CONTRACT,
    RECORD_SCHEMA_URI,
    RECORD_TYPES,
    SOURCE_CHECKSUM_PATTERN,
    SOURCE_TYPES,
    EVIDENCE_CONTRACT,
    EVIDENCE_ROLES,
    SOURCE_RELATIONSHIPS,
    INDICATOR_GOVERNANCE_CONTRACT,
    INDICATOR_STATUSES,
    INDICATOR_FREQUENCIES,
    INDICATOR_AGGREGATIONS,
    METHODOLOGY_STATUSES,
    FRAMEWORK_MAPPING_RELATIONSHIPS,
    OBSERVATION_LINEAGE_CONTRACT,
    QUESTION_TYPES,
    QUESTION_STATUSES,
    INSTRUMENT_TYPES,
    DATASET_ACCESS_LEVELS,
    OBSERVATION_ROLES,
    OBSERVATION_QUALITY_STATUSES,
)
from ._contract import DIRECTIONS, REVIEW_STATUSES, SIGNAL_STATUSES

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # Portable repository checks still use the strict fallback below.
    Draft202012Validator = None
    FormatChecker = None


class RecordValidationError(ValueError):
    """Raised when a record violates the canonical data contract."""


def schema() -> dict[str, Any]:
    path = resources.files("catalyst_data").joinpath("schemas/catalyst_data_record_1_0.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _path(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path)
    return location or "record"


def _iso_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RecordValidationError(f"{field} must be an ISO 8601 date-time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordValidationError(f"{field} must be an ISO 8601 date-time") from exc


def _strict_fallback(record: Mapping[str, Any]) -> None:
    required = {
        "$schema", "schema_version", "record_id", "record_type", "created_at", "updated_at",
        "producer", "entity", "indicator", "period", "measurement", "source", "confidence",
        "review", "method", "extensions"
    }
    unknown = set(record) - (required | {"evidence_chain", "indicator_governance", "observation_lineage"})
    missing = required - set(record)
    if missing:
        raise RecordValidationError(f"record is missing required fields: {', '.join(sorted(missing))}")
    if unknown:
        raise RecordValidationError(f"record contains unknown fields: {', '.join(sorted(unknown))}")
    if record["$schema"] != RECORD_SCHEMA_URI or record["schema_version"] != RECORD_CONTRACT:
        raise RecordValidationError("record schema identifier is not catalyst-data-record/1.0")
    if record["record_type"] not in RECORD_TYPES:
        raise RecordValidationError("record_type is invalid")
    if not re.fullmatch(ID_PATTERN, str(record["record_id"])):
        raise RecordValidationError("record_id is invalid")

    expected_nested = {
        "producer": {"name", "version", "component"},
        "entity": {"id", "name", "type", "external_ids"},
        "indicator": {"id", "name", "unit", "direction", "framework", "version"},
        "period": {"id", "label", "start_date", "end_date"},
        "measurement": {"baseline", "current", "percent_change"},
        "source": {"id", "name", "type", "url", "publisher", "license", "retrieved_at", "citation", "checksum", "access_notes"},
        "confidence": {"score", "scale", "basis"},
        "review": {"status", "signal_status", "reviewer_notes"},
        "method": {"notes", "assumptions", "limitations", "uncertainty", "quality_flags"},
    }
    for name, keys in expected_nested.items():
        value = record[name]
        if not isinstance(value, Mapping):
            raise RecordValidationError(f"{name} must be an object")
        missing_keys = keys - set(value)
        unknown_keys = set(value) - keys
        if missing_keys or unknown_keys:
            details = []
            if missing_keys:
                details.append("missing " + ", ".join(sorted(missing_keys)))
            if unknown_keys:
                details.append("unknown " + ", ".join(sorted(unknown_keys)))
            raise RecordValidationError(f"{name} has invalid fields: {'; '.join(details)}")

    for group in ("entity", "indicator", "period", "source"):
        if not re.fullmatch(ID_PATTERN, str(record[group]["id"])):
            raise RecordValidationError(f"{group}.id is invalid")
    if record["producer"]["component"] not in PRODUCER_COMPONENTS:
        raise RecordValidationError("producer.component is invalid")
    if record["indicator"]["direction"] not in DIRECTIONS:
        raise RecordValidationError("indicator.direction is invalid")
    if record["source"]["type"] not in SOURCE_TYPES:
        raise RecordValidationError("source.type is invalid")
    if record["review"]["status"] not in REVIEW_STATUSES:
        raise RecordValidationError("review.status is invalid")
    if record["review"]["signal_status"] not in SIGNAL_STATUSES:
        raise RecordValidationError("review.signal_status is invalid")
    score = record["confidence"]["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or not 0 <= float(score) <= 100:
        raise RecordValidationError("confidence.score must be a finite number between 0 and 100")
    if record["confidence"]["scale"] != "0-100":
        raise RecordValidationError("confidence.scale must be 0-100")
    checksum = record["source"]["checksum"]
    if checksum is not None and not re.fullmatch(SOURCE_CHECKSUM_PATTERN, str(checksum)):
        raise RecordValidationError("source.checksum is invalid")
    flags = record["method"]["quality_flags"]
    if not isinstance(flags, list) or len(flags) != len(set(flags)) or any(flag not in QUALITY_FLAGS for flag in flags):
        raise RecordValidationError("method.quality_flags is invalid")
    chain = record.get("evidence_chain")
    if chain is not None:
        if not isinstance(chain, Mapping) or chain.get("schema_version") != EVIDENCE_CONTRACT:
            raise RecordValidationError("evidence_chain schema version is invalid")
        expected = {"schema_version", "sources", "relationships", "transformations", "gaps", "completeness_score"}
        if set(chain) != expected:
            raise RecordValidationError("evidence_chain has invalid fields")
        if not isinstance(chain["sources"], list) or not chain["sources"]:
            raise RecordValidationError("evidence_chain.sources must contain at least one source")
        for link in chain["sources"]:
            if not isinstance(link, Mapping) or link.get("role") not in EVIDENCE_ROLES:
                raise RecordValidationError("evidence_chain source role is invalid")
        for relationship in chain["relationships"]:
            if relationship.get("predicate") not in SOURCE_RELATIONSHIPS:
                raise RecordValidationError("evidence_chain relationship is invalid")
        score = chain["completeness_score"]
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise RecordValidationError("evidence_chain.completeness_score must be an integer from 0 to 100")


    governance = record.get("indicator_governance")
    if governance is not None:
        if not isinstance(governance, Mapping) or governance.get("schema_version") != INDICATOR_GOVERNANCE_CONTRACT:
            raise RecordValidationError("indicator_governance schema version is invalid")
        required_governance = {"schema_version", "namespace", "code", "domain", "custodian", "status", "aliases", "definition", "frequency", "aggregation", "disaggregation_dimensions", "numerator", "denominator", "unit", "methodology", "framework_mappings", "compatibility"}
        if set(governance) != required_governance:
            raise RecordValidationError("indicator_governance has invalid fields")
        if governance["status"] not in INDICATOR_STATUSES:
            raise RecordValidationError("indicator_governance.status is invalid")
        if governance["frequency"] not in INDICATOR_FREQUENCIES:
            raise RecordValidationError("indicator_governance.frequency is invalid")
        if governance["aggregation"] not in INDICATOR_AGGREGATIONS:
            raise RecordValidationError("indicator_governance.aggregation is invalid")
        if governance["methodology"].get("status") not in METHODOLOGY_STATUSES:
            raise RecordValidationError("indicator_governance.methodology.status is invalid")
        for mapping in governance["framework_mappings"]:
            if mapping.get("relationship") not in FRAMEWORK_MAPPING_RELATIONSHIPS:
                raise RecordValidationError("indicator_governance framework mapping is invalid")

    lineage = record.get("observation_lineage")
    if lineage is not None:
        if not isinstance(lineage, Mapping) or lineage.get("schema_version") != OBSERVATION_LINEAGE_CONTRACT:
            raise RecordValidationError("observation_lineage schema version is invalid")
        required_lineage = {"schema_version", "questions", "instruments", "datasets", "batches", "observations", "transformations", "completeness_score"}
        if set(lineage) != required_lineage:
            raise RecordValidationError("observation_lineage has invalid fields")
        if not all(isinstance(lineage.get(name), list) and lineage[name] for name in ("questions", "instruments", "datasets", "batches", "observations")):
            raise RecordValidationError("observation_lineage requires questions, instruments, datasets, batches, and observations")
        for question in lineage["questions"]:
            if question.get("type") not in QUESTION_TYPES or question.get("status") not in QUESTION_STATUSES:
                raise RecordValidationError("observation_lineage question type or status is invalid")
        for instrument in lineage["instruments"]:
            if instrument.get("type") not in INSTRUMENT_TYPES:
                raise RecordValidationError("observation_lineage instrument type is invalid")
        for dataset in lineage["datasets"]:
            if dataset.get("access") not in DATASET_ACCESS_LEVELS:
                raise RecordValidationError("observation_lineage dataset access is invalid")
        for observation in lineage["observations"]:
            if observation.get("role") not in OBSERVATION_ROLES or observation.get("quality_status") not in OBSERVATION_QUALITY_STATUSES:
                raise RecordValidationError("observation_lineage observation role or quality status is invalid")
        from .lineage import validate_observation_lineage
        try:
            validate_observation_lineage(lineage, record)
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordValidationError(str(exc)) from exc

    extensions = record["extensions"]
    if not isinstance(extensions, Mapping):
        raise RecordValidationError("extensions must be an object")
    for key in extensions:
        if not re.fullmatch(EXTENSION_KEY_PATTERN, str(key)):
            raise RecordValidationError(f"extensions key is invalid: {key}")


def validate_record(record: Mapping[str, Any]) -> None:
    """Validate JSON Schema shape and cross-field semantic invariants."""
    if not isinstance(record, Mapping):
        raise RecordValidationError("record must be an object")
    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema(), format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path))
        if errors:
            error = errors[0]
            raise RecordValidationError(f"{_path(error)}: {error.message}")
    else:
        _strict_fallback(record)

    created = _iso_datetime(record["created_at"], "created_at")
    updated = _iso_datetime(record["updated_at"], "updated_at")
    if updated < created:
        raise RecordValidationError("updated_at cannot be earlier than created_at")

    period = record["period"]
    if period["start_date"] and period["end_date"] and period["start_date"] > period["end_date"]:
        raise RecordValidationError("period.end_date cannot be earlier than period.start_date")

    measurement = record["measurement"]
    for field in ("baseline", "current", "percent_change"):
        value = measurement[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))):
            raise RecordValidationError(f"measurement.{field} must be a finite number or null")


def jsonschema_available() -> bool:
    return Draft202012Validator is not None
