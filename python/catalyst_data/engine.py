from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ._contract import (
    CAUTION_BELOW,
    CONFIDENCE_MAXIMUM,
    CONFIDENCE_MINIMUM,
    DIRECTIONS,
    MISSING_SOURCE_NAMES,
    NEEDS_EVIDENCE_BELOW,
    TRACE_PATH,
)

ENTITY_TYPES = (
    "country",
    "organization",
    "project",
    "program",
    "site",
    "policy",
    "persona",
    "experiment",
    "dataset",
    "other",
)


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def percent_change(baseline: float, current: float) -> Optional[float]:
    """Return percent change, or None when a zero baseline makes it undefined."""
    baseline_value = _number(baseline, "values.baseline")
    current_value = _number(current, "values.current")
    if baseline_value == 0:
        return None
    return round(((current_value - baseline_value) / abs(baseline_value)) * 100.0, 2)


def source_is_missing(source_name: Any) -> bool:
    normalized = "" if source_name is None else str(source_name).strip()
    return normalized in MISSING_SOURCE_NAMES


def classify_review(confidence: float, source_name: Any) -> str:
    confidence_value = _number(confidence, "confidence")
    if not CONFIDENCE_MINIMUM <= confidence_value <= CONFIDENCE_MAXIMUM:
        raise ValueError(
            f"confidence must be between {CONFIDENCE_MINIMUM} and {CONFIDENCE_MAXIMUM}"
        )
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


def classify_record(
    confidence: float,
    change: Optional[float],
    direction: str,
    source_name: Any = "source supplied",
) -> str:
    """Compatibility wrapper returning the canonical review status.

    Signal direction is intentionally available through ``classify_signal`` and is
    no longer mixed with evidence readiness.
    """
    classify_signal(change, direction)
    return classify_review(confidence, source_name)


def validate_payload(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    for section in ("entity", "indicator", "values", "source"):
        if section not in payload or not isinstance(payload[section], dict):
            raise ValueError(f"{section} must be an object")

    entity = payload["entity"]
    indicator = payload["indicator"]
    values = payload["values"]

    if not str(entity.get("name", "")).strip():
        raise ValueError("entity.name is required")
    entity_type = str(entity.get("type", "other"))
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity.type must be one of: {', '.join(ENTITY_TYPES)}")

    if not str(indicator.get("name", "")).strip():
        raise ValueError("indicator.name is required")
    direction = str(indicator.get("direction", "neutral"))
    if direction not in DIRECTIONS:
        raise ValueError(f"indicator.direction must be one of: {', '.join(DIRECTIONS)}")

    if not str(payload.get("period", "")).strip():
        raise ValueError("period is required")

    _number(values.get("baseline"), "values.baseline")
    _number(values.get("current"), "values.current")
    confidence = _number(payload.get("confidence"), "confidence")
    if not CONFIDENCE_MINIMUM <= confidence <= CONFIDENCE_MAXIMUM:
        raise ValueError(
            f"confidence must be between {CONFIDENCE_MINIMUM} and {CONFIDENCE_MAXIMUM}"
        )


@dataclass
class CatalystDataRecord:
    entity: Dict[str, str]
    indicator: Dict[str, str]
    period: str
    values: Dict[str, Optional[float]]
    source: Dict[str, str]
    confidence: float
    review_status: str
    signal_status: str
    method_notes: str
    trace_path: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    validate_payload(payload)
    entity = payload["entity"]
    indicator = payload["indicator"]
    values = payload["values"]
    source = payload["source"]
    baseline = _number(values["baseline"], "values.baseline")
    current = _number(values["current"], "values.current")
    confidence = _number(payload["confidence"], "confidence")
    direction = str(indicator.get("direction", "neutral"))
    source_name = str(source.get("name", "")).strip() or "Unspecified source"
    change = percent_change(baseline, current)

    return CatalystDataRecord(
        entity={"name": str(entity["name"]).strip(), "type": str(entity.get("type", "other"))},
        indicator={
            "name": str(indicator["name"]).strip(),
            "unit": str(indicator.get("unit", "unit")).strip() or "unit",
            "direction": direction,
        },
        period=str(payload["period"]).strip(),
        values={"baseline": baseline, "current": current, "percent_change": change},
        source={
            "name": source_name,
            "type": str(source.get("type", "unspecified")).strip() or "unspecified",
        },
        confidence=confidence,
        review_status=classify_review(confidence, source_name),
        signal_status=classify_signal(change, direction),
        method_notes=str(payload.get("method_notes", "")).strip(),
        trace_path=list(TRACE_PATH),
    ).to_dict()


def brief_markdown(record: Dict[str, Any]) -> str:
    values = record["values"]
    percent = (
        "indeterminate (zero baseline)"
        if values["percent_change"] is None
        else f'{values["percent_change"]}%'
    )
    return f"""# Catalyst Data Brief: {record['entity']['name']}

## Measurement

- **Indicator:** {record['indicator']['name']}
- **Period:** {record['period']}
- **Baseline:** {values['baseline']} {record['indicator']['unit']}
- **Current:** {values['current']} {record['indicator']['unit']}
- **Percent change:** {percent}
- **Source:** {record['source']['name']}
- **Confidence:** {record['confidence']}%
- **Review status:** {record['review_status']}
- **Signal status:** {record['signal_status']}

## Trace Path

`{' → '.join(record['trace_path'])}`

## Method Notes

{record.get('method_notes') or 'No method notes provided.'}

## Boundary

This brief is a structured evidence artifact. It does not certify compliance, verify impact, or replace professional review.
"""
