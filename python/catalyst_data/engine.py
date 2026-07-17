from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from ._contract import (
    CAUTION_BELOW,
    CONFIDENCE_MAXIMUM,
    CONFIDENCE_MINIMUM,
    DIRECTIONS,
    MISSING_SOURCE_NAMES,
    NEEDS_EVIDENCE_BELOW,
)
from ._record_contract import (
    ENTITY_TYPES,
    EXTENSION_KEY_PATTERN,
    PRODUCER_COMPONENTS,
    QUALITY_FLAGS,
    RECORD_CONTRACT,
    RECORD_SCHEMA_URI,
    SOURCE_TYPES,
)
from ._version import __version__
from .validation import RecordValidationError, validate_record
from .provenance import normalize_evidence_chain, validate_evidence_chain_semantics


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _optional_number(value: Any, field: str) -> Optional[float]:
    if value is None or value == "":
        return None
    return _number(value, field)


def _text(value: Any, field: str, *, required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    result = str(value).strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    return result or None


def _list_of_text(value: Any, field: str) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        values: Iterable[Any] = value.split("\n")
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError(f"{field} must be an array of strings")
    result: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _timestamp(value: Any, fallback: datetime) -> str:
    if value is None or value == "":
        candidate = fallback
    elif isinstance(value, datetime):
        candidate = value
    else:
        text = str(value).strip()
        try:
            candidate = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamps must be ISO 8601 date-times") from exc
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    candidate = candidate.astimezone(timezone.utc).replace(microsecond=0)
    return candidate.isoformat().replace("+00:00", "Z")


def slug(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized[:64] or "unspecified"


def stable_id(kind: str, *parts: Any) -> str:
    canonical = json.dumps([str(part).strip().lower() for part in parts], separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    anchor = slug(next((part for part in parts if str(part).strip()), kind))
    return f"{slug(kind)}:{anchor}:{digest}"


def percent_change(baseline: Optional[float], current: float) -> Optional[float]:
    """Return percent change, or None when a missing/zero baseline makes it undefined."""
    baseline_value = _optional_number(baseline, "measurement.baseline")
    current_value = _number(current, "measurement.current")
    if baseline_value is None or baseline_value == 0:
        return None
    return round(((current_value - baseline_value) / abs(baseline_value)) * 100.0, 2)


def source_is_missing(source_name: Any) -> bool:
    normalized = "" if source_name is None else str(source_name).strip()
    return normalized in MISSING_SOURCE_NAMES


def classify_review(confidence: float, source_name: Any) -> str:
    confidence_value = _number(confidence, "confidence.score")
    if not CONFIDENCE_MINIMUM <= confidence_value <= CONFIDENCE_MAXIMUM:
        raise ValueError(f"confidence.score must be between {CONFIDENCE_MINIMUM} and {CONFIDENCE_MAXIMUM}")
    if source_is_missing(source_name):
        return "missing source"
    if confidence_value < NEEDS_EVIDENCE_BELOW:
        return "needs evidence"
    if confidence_value < CAUTION_BELOW:
        return "reviewable with caution"
    return "reviewable"


def classify_signal(change: Optional[float], direction: str) -> str:
    if direction not in DIRECTIONS:
        raise ValueError(f"indicator.direction must be one of: {', '.join(DIRECTIONS)}")
    if change is None:
        return "indeterminate"
    if change == 0:
        return "unchanged"
    if direction == "neutral":
        return "descriptive"
    improving = change > 0 if direction == "higher" else change < 0
    return "improving" if improving else "declining"


def classify_record(confidence: float, change: Optional[float], direction: str, source_name: Any = "source supplied") -> str:
    classify_signal(change, direction)
    return classify_review(confidence, source_name)


def _legacy_source(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    source = payload.get("source")
    return source if isinstance(source, Mapping) else {}


def is_canonical_record(payload: Mapping[str, Any]) -> bool:
    return payload.get("schema_version") == RECORD_CONTRACT


def convert_legacy_record(
    payload: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    producer_component: str = "migration-tool",
) -> Dict[str, Any]:
    """Upgrade an unversioned v1.0.x authoring payload or export to record/1.0."""
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")
    if producer_component not in PRODUCER_COMPONENTS:
        raise ValueError("producer component is invalid")

    entity = payload.get("entity")
    indicator = payload.get("indicator")
    values = payload.get("values", payload.get("measurement"))
    source = _legacy_source(payload)
    if not isinstance(entity, Mapping):
        raise ValueError("entity must be an object")
    if not isinstance(indicator, Mapping):
        raise ValueError("indicator must be an object")
    if not isinstance(values, Mapping):
        raise ValueError("values must be an object")

    entity_name = _text(entity.get("name"), "entity.name", required=True)
    entity_type = str(entity.get("type", "other")).strip() or "other"
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity.type must be one of: {', '.join(ENTITY_TYPES)}")
    indicator_name = _text(indicator.get("name"), "indicator.name", required=True)
    unit = _text(indicator.get("unit"), "indicator.unit", required=True)
    direction = str(indicator.get("direction", "neutral")).strip() or "neutral"
    if direction not in DIRECTIONS:
        raise ValueError(f"indicator.direction must be one of: {', '.join(DIRECTIONS)}")
    period_value = payload.get("period")
    period_label = _text(period_value.get("label") if isinstance(period_value, Mapping) else period_value, "period", required=True)

    baseline = _optional_number(values.get("baseline"), "measurement.baseline")
    current = _number(values.get("current"), "measurement.current")
    change = percent_change(baseline, current)

    source_name = _text(source.get("name"), "source.name") or "Unspecified source"
    source_type = str(source.get("type", "unspecified")).strip() or "unspecified"
    if source_type not in SOURCE_TYPES:
        source_type = "other"
    confidence_value = payload.get("confidence", 0)
    if isinstance(confidence_value, Mapping):
        confidence_score = _number(confidence_value.get("score"), "confidence.score")
        confidence_basis = _text(confidence_value.get("basis"), "confidence.basis")
    else:
        confidence_score = _number(confidence_value, "confidence.score")
        confidence_basis = _text(payload.get("confidence_basis"), "confidence_basis")
    if not CONFIDENCE_MINIMUM <= confidence_score <= CONFIDENCE_MAXIMUM:
        raise ValueError(f"confidence.score must be between {CONFIDENCE_MINIMUM} and {CONFIDENCE_MAXIMUM}")

    method_value = payload.get("method") if isinstance(payload.get("method"), Mapping) else {}
    notes = _text(method_value.get("notes", payload.get("method_notes")), "method.notes") or ""
    assumptions = _list_of_text(method_value.get("assumptions", payload.get("assumptions")), "method.assumptions")
    limitations = _list_of_text(method_value.get("limitations", payload.get("limitations")), "method.limitations")
    uncertainty = _text(method_value.get("uncertainty", payload.get("uncertainty")), "method.uncertainty")
    quality_flags = _list_of_text(method_value.get("quality_flags", payload.get("quality_flags")), "method.quality_flags")
    invalid_flags = sorted(set(quality_flags) - set(QUALITY_FLAGS))
    if invalid_flags:
        raise ValueError(f"method.quality_flags contains unsupported values: {', '.join(invalid_flags)}")

    extensions = deepcopy(payload.get("extensions", {}))
    if not isinstance(extensions, dict):
        raise ValueError("extensions must be an object")
    for key in extensions:
        if not re.fullmatch(EXTENSION_KEY_PATTERN, str(key)):
            raise ValueError(f"extensions key is invalid: {key}")

    current_time = now or datetime.now(timezone.utc)
    created_at = _timestamp(payload.get("created_at"), current_time)
    updated_at = _timestamp(payload.get("updated_at"), datetime.fromisoformat(created_at.replace("Z", "+00:00")))

    entity_id = _text(entity.get("id"), "entity.id") or stable_id("entity", entity_type, entity_name)
    indicator_id = _text(indicator.get("id"), "indicator.id") or stable_id("indicator", indicator_name, unit, direction)
    period_id = (
        _text(period_value.get("id"), "period.id") if isinstance(period_value, Mapping) else None
    ) or stable_id("period", period_label)
    source_id = _text(source.get("id"), "source.id") or stable_id(
        "source", source_name, source.get("publisher") or "", source.get("url") or ""
    )
    record_id = _text(payload.get("record_id"), "record_id") or stable_id(
        "measurement", entity_id, indicator_id, period_id, source_id
    )

    record: Dict[str, Any] = {
        "$schema": RECORD_SCHEMA_URI,
        "schema_version": RECORD_CONTRACT,
        "record_id": record_id,
        "record_type": "measurement",
        "created_at": created_at,
        "updated_at": updated_at,
        "producer": {
            "name": "Catalyst Data",
            "version": __version__,
            "component": producer_component,
        },
        "entity": {
            "id": entity_id,
            "name": entity_name,
            "type": entity_type,
            "external_ids": deepcopy(entity.get("external_ids", {})),
        },
        "indicator": {
            "id": indicator_id,
            "name": indicator_name,
            "unit": unit,
            "direction": direction,
            "framework": _text(indicator.get("framework"), "indicator.framework"),
            "version": _text(indicator.get("version"), "indicator.version") or "1.0",
        },
        "period": {
            "id": period_id,
            "label": period_label,
            "start_date": _text(period_value.get("start_date"), "period.start_date") if isinstance(period_value, Mapping) else None,
            "end_date": _text(period_value.get("end_date"), "period.end_date") if isinstance(period_value, Mapping) else None,
        },
        "measurement": {"baseline": baseline, "current": current, "percent_change": change},
        "source": {
            "id": source_id,
            "name": source_name,
            "type": source_type,
            "url": _text(source.get("url"), "source.url"),
            "publisher": _text(source.get("publisher"), "source.publisher"),
            "license": _text(source.get("license"), "source.license"),
            "retrieved_at": _text(source.get("retrieved_at"), "source.retrieved_at"),
            "citation": _text(source.get("citation"), "source.citation"),
            "checksum": _text(source.get("checksum"), "source.checksum"),
            "access_notes": _text(source.get("access_notes"), "source.access_notes"),
        },
        "confidence": {"score": confidence_score, "scale": "0-100", "basis": confidence_basis},
        "review": {
            "status": classify_review(confidence_score, source_name),
            "signal_status": classify_signal(change, direction),
            "reviewer_notes": _text(
                payload.get("reviewer_notes") or (payload.get("review", {}).get("reviewer_notes") if isinstance(payload.get("review"), Mapping) else None),
                "review.reviewer_notes",
            ) or "",
        },
        "method": {
            "notes": notes,
            "assumptions": assumptions,
            "limitations": limitations,
            "uncertainty": uncertainty,
            "quality_flags": quality_flags,
        },
        "extensions": extensions,
    }
    record["evidence_chain"] = normalize_evidence_chain(
        record["source"],
        payload.get("evidence_chain") or ({"sources": payload.get("sources", [])} if payload.get("sources") else None),
        method=record["method"],
        confidence=record["confidence"],
        occurred_at=updated_at,
    )
    validate_record_semantics(record)
    validate_record(record)
    return record


def validate_record_semantics(record: Mapping[str, Any]) -> None:
    measurement = record["measurement"]
    expected_change = percent_change(measurement["baseline"], measurement["current"])
    actual_change = measurement["percent_change"]
    if expected_change != actual_change:
        raise RecordValidationError(
            f"measurement.percent_change must be {expected_change!r} for the supplied baseline and current values"
        )
    expected_review = classify_review(record["confidence"]["score"], record["source"]["name"])
    if record["review"]["status"] != expected_review:
        raise RecordValidationError(f"review.status must be {expected_review!r}")
    expected_signal = classify_signal(actual_change, record["indicator"]["direction"])
    if record["review"]["signal_status"] != expected_signal:
        raise RecordValidationError(f"review.signal_status must be {expected_signal!r}")
    try:
        validate_evidence_chain_semantics(record)
    except ValueError as exc:
        raise RecordValidationError(str(exc)) from exc


def build_record(
    payload: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    producer_component: str = "python-engine",
) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")
    if is_canonical_record(payload):
        record = deepcopy(dict(payload))
        if "evidence_chain" not in record:
            record["evidence_chain"] = normalize_evidence_chain(
                record["source"], None, method=record["method"], confidence=record["confidence"], occurred_at=record["updated_at"]
            )
        validate_record(record)
        validate_record_semantics(record)
        return record
    return convert_legacy_record(payload, now=now, producer_component=producer_component)


def validate_payload(payload: Mapping[str, Any]) -> None:
    """Compatibility API: validate any accepted input by constructing its canonical record."""
    build_record(payload)


def brief_markdown(record: Mapping[str, Any]) -> str:
    validate_record(record)
    validate_record_semantics(record)
    values = record["measurement"]
    percent = "indeterminate (missing or zero baseline)" if values["percent_change"] is None else f'{values["percent_change"]}%'
    source = record["source"]
    citation = source["citation"] or source["name"]
    flags = ", ".join(record["method"]["quality_flags"]) or "None"
    return f"""# Catalyst Data Brief: {record['entity']['name']}

## Record Contract

- **Schema:** `{record['schema_version']}`
- **Record ID:** `{record['record_id']}`
- **Created:** {record['created_at']}
- **Updated:** {record['updated_at']}
- **Producer:** {record['producer']['name']} v{record['producer']['version']} ({record['producer']['component']})

## Measurement

- **Indicator:** {record['indicator']['name']} ({record['indicator']['version']})
- **Period:** {record['period']['label']}
- **Baseline:** {values['baseline']} {record['indicator']['unit']}
- **Current:** {values['current']} {record['indicator']['unit']}
- **Percent change:** {percent}
- **Confidence:** {record['confidence']['score']}% ({record['confidence']['basis'] or 'basis not supplied'})
- **Review status:** {record['review']['status']}
- **Signal status:** {record['review']['signal_status']}

## Source and Provenance

- **Source:** {source['name']}
- **Publisher:** {source['publisher'] or 'Not supplied'}
- **License:** {source['license'] or 'Not supplied'}
- **Citation:** {citation}
- **Retrieved:** {source['retrieved_at'] or 'Not supplied'}
- **Checksum:** {source['checksum'] or 'Not supplied'}
- **Evidence sources:** {len(record.get('evidence_chain', {}).get('sources', [source]))}
- **Evidence completeness:** {record.get('evidence_chain', {}).get('completeness_score', 'Not assessed')}%
- **Open evidence gaps:** {len(record.get('evidence_chain', {}).get('gaps', []))}

## Method

{record['method']['notes'] or 'No method notes provided.'}

- **Assumptions:** {'; '.join(record['method']['assumptions']) or 'None supplied'}
- **Limitations:** {'; '.join(record['method']['limitations']) or 'None supplied'}
- **Uncertainty:** {record['method']['uncertainty'] or 'Not supplied'}
- **Quality flags:** {flags}
- **Reviewer notes:** {record['review']['reviewer_notes'] or 'None supplied'}

## Boundary

This brief is a structured evidence artifact. It does not certify compliance, verify impact, or replace professional review.
"""
