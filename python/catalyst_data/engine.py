from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

TRACE_PATH = ["entity", "indicator", "period", "measurement", "source", "confidence", "review"]

def percent_change(baseline: float, current: float) -> float:
    if baseline == 0:
        return 0.0
    return round(((current - baseline) / abs(baseline)) * 100.0, 2)

def classify_record(confidence: float, change: float, direction: str) -> str:
    if confidence < 40:
        return "needs evidence"
    if direction == "neutral":
        return "reviewable" if confidence >= 70 else "reviewable with caution"
    improving = change >= 0 if direction == "higher" else change <= 0
    if confidence >= 70 and improving:
        return "strong signal"
    if confidence >= 55:
        return "reviewable with caution"
    return "needs evidence"

@dataclass
class CatalystDataRecord:
    entity: Dict[str, str]
    indicator: Dict[str, str]
    period: str
    values: Dict[str, float]
    source: Dict[str, str]
    confidence: float
    review_status: str
    method_notes: str
    trace_path: List[str]
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def build_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    entity = payload.get("entity", {})
    indicator = payload.get("indicator", {})
    values = payload.get("values", {})
    source = payload.get("source", {})
    baseline = float(values.get("baseline", 0))
    current = float(values.get("current", 0))
    confidence = float(payload.get("confidence", 0))
    direction = indicator.get("direction", "neutral")
    change = percent_change(baseline, current)
    return CatalystDataRecord(
        entity={"name": entity.get("name", "Unnamed entity"), "type": entity.get("type", "other")},
        indicator={"name": indicator.get("name", "Unnamed indicator"), "unit": indicator.get("unit", "unit"), "direction": direction},
        period=str(payload.get("period", "unspecified")),
        values={"baseline": baseline, "current": current, "percent_change": change},
        source={"name": source.get("name", "Unspecified source"), "type": source.get("type", "unspecified")},
        confidence=confidence,
        review_status=classify_record(confidence, change, direction),
        method_notes=payload.get("method_notes", ""),
        trace_path=TRACE_PATH,
    ).to_dict()

def brief_markdown(record: Dict[str, Any]) -> str:
    values = record["values"]
    return f"""# Catalyst Data Brief: {record['entity']['name']}

## Measurement

- **Indicator:** {record['indicator']['name']}
- **Period:** {record['period']}
- **Baseline:** {values['baseline']} {record['indicator']['unit']}
- **Current:** {values['current']} {record['indicator']['unit']}
- **Percent change:** {values['percent_change']}%
- **Source:** {record['source']['name']}
- **Confidence:** {record['confidence']}%
- **Review status:** {record['review_status']}

## Trace Path

`{' → '.join(record['trace_path'])}`

## Method Notes

{record.get('method_notes') or 'No method notes provided.'}

## Boundary

This brief is a structured evidence artifact. It does not certify compliance, verify impact, or replace professional review.
"""
