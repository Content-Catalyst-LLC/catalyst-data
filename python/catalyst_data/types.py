"""Typed mappings aligned with catalyst-data-record/1.0.

JSON Schema remains the runtime authority. These TypedDicts provide editor and
static-analysis support without replacing validation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ProducerRecord(TypedDict):
    name: str
    version: str
    component: str


class EntityRecord(TypedDict):
    id: str
    name: str
    type: str
    external_ids: Dict[str, str]


class IndicatorRecord(TypedDict):
    id: str
    name: str
    unit: str
    direction: str
    framework: Optional[str]
    version: str


class PeriodRecord(TypedDict):
    id: str
    label: str
    start_date: Optional[str]
    end_date: Optional[str]


class MeasurementRecord(TypedDict):
    baseline: Optional[float]
    current: float
    percent_change: Optional[float]


class SourceRecord(TypedDict):
    id: str
    name: str
    type: str
    url: Optional[str]
    publisher: Optional[str]
    license: Optional[str]
    retrieved_at: Optional[str]
    citation: Optional[str]
    checksum: Optional[str]
    access_notes: Optional[str]




class EvidenceLocator(TypedDict):
    page: Optional[str]
    section: Optional[str]
    quote: Optional[str]
    fragment: Optional[str]


class EvidenceSourceLink(TypedDict):
    role: str
    source: SourceRecord
    locator: EvidenceLocator
    supports: List[str]
    notes: Optional[str]


class SourceRelationship(TypedDict):
    subject_source_id: str
    predicate: str
    object_source_id: str
    notes: Optional[str]


class EvidenceTransformation(TypedDict):
    id: str
    operation: str
    description: str
    software: Optional[str]
    parameters: Dict[str, Any]
    occurred_at: Optional[str]


class EvidenceGap(TypedDict):
    code: str
    severity: str
    description: str


class EvidenceChain(TypedDict):
    schema_version: str
    sources: List[EvidenceSourceLink]
    relationships: List[SourceRelationship]
    transformations: List[EvidenceTransformation]
    gaps: List[EvidenceGap]
    completeness_score: int


class ConfidenceRecord(TypedDict):
    score: float
    scale: str
    basis: Optional[str]


class ReviewRecord(TypedDict):
    status: str
    signal_status: str
    reviewer_notes: str


class MethodRecord(TypedDict):
    notes: str
    assumptions: List[str]
    limitations: List[str]
    uncertainty: Optional[str]
    quality_flags: List[str]


CatalystDataRecord = TypedDict(
    "CatalystDataRecord",
    {
        "$schema": str,
        "schema_version": str,
        "record_id": str,
        "record_type": str,
        "created_at": str,
        "updated_at": str,
        "producer": ProducerRecord,
        "entity": EntityRecord,
        "indicator": IndicatorRecord,
        "period": PeriodRecord,
        "measurement": MeasurementRecord,
        "source": SourceRecord,
        "evidence_chain": EvidenceChain,
        "confidence": ConfidenceRecord,
        "review": ReviewRecord,
        "method": MethodRecord,
        "extensions": Dict[str, Any],
    },
)
