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


class IndicatorComponent(TypedDict):
    name: str
    unit_id: Optional[str]
    description: Optional[str]


class UnitDefinition(TypedDict):
    id: str
    symbol: str
    name: str
    dimension: str
    canonical_unit_id: str
    conversion_factor: float
    conversion_offset: float


class MethodologyDefinition(TypedDict):
    id: str
    version: str
    title: str
    description: str
    formula: Optional[str]
    references: List[str]
    status: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    revision_notes: Optional[str]


class FrameworkMapping(TypedDict):
    framework: str
    code: str
    relationship: str
    notes: Optional[str]


class CompatibilityDefinition(TypedDict):
    comparable_versions: List[str]
    required_dimensions: List[str]
    methodology_equivalence: List[str]
    notes: Optional[str]


class IndicatorGovernance(TypedDict):
    schema_version: str
    namespace: str
    code: str
    domain: str
    custodian: str
    status: str
    aliases: List[str]
    definition: str
    frequency: str
    aggregation: str
    disaggregation_dimensions: List[str]
    numerator: Optional[IndicatorComponent]
    denominator: Optional[IndicatorComponent]
    unit: UnitDefinition
    methodology: MethodologyDefinition
    framework_mappings: List[FrameworkMapping]
    compatibility: CompatibilityDefinition


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


class ResearchQuestion(TypedDict):
    id: str
    text: str
    type: str
    decision_context: Optional[str]
    status: str
    owner: Optional[str]


class CollectionField(TypedDict, total=False):
    name: str
    data_type: str
    unit_id: Optional[str]
    description: Optional[str]
    required: bool
    nullable: bool


class InstrumentDefinition(TypedDict):
    id: str
    name: str
    type: str
    version: str
    description: Optional[str]
    protocol: Optional[str]
    provider: Optional[str]
    calibration: Optional[str]
    fields: List[CollectionField]


class DatasetDefinition(TypedDict):
    id: str
    name: str
    version: str
    description: Optional[str]
    license: Optional[str]
    access: str
    checksum: Optional[str]
    fields: List[CollectionField]


class ObservationBatch(TypedDict):
    id: str
    dataset_id: str
    instrument_id: str
    collected_at: Optional[str]
    received_at: Optional[str]
    collector: Optional[str]
    protocol: Optional[str]
    record_count: int
    notes: Optional[str]


class ObservationRecord(TypedDict):
    id: str
    batch_id: str
    role: str
    observed_at: Optional[str]
    value: Optional[float]
    value_text: Optional[str]
    unit_id: Optional[str]
    quality_status: str
    missing_reason: Optional[str]
    censoring: Optional[str]
    outlier: bool
    imputation: Optional[str]
    dimensions: Dict[str, str]
    raw_payload: Dict[str, Any]


class ObservationTransformation(TypedDict):
    id: str
    operation: str
    description: str
    software: Optional[str]
    parameters: Dict[str, Any]
    input_observation_ids: List[str]
    output_measurement_fields: List[str]
    occurred_at: Optional[str]


class ObservationLineage(TypedDict):
    schema_version: str
    questions: List[ResearchQuestion]
    instruments: List[InstrumentDefinition]
    datasets: List[DatasetDefinition]
    batches: List[ObservationBatch]
    observations: List[ObservationRecord]
    transformations: List[ObservationTransformation]
    completeness_score: int



class ReviewQualityAssessment(TypedDict):
    completeness: int
    validity: int
    consistency: int
    timeliness: int
    provenance: int
    uncertainty: int
    overall: int
    basis: Dict[str, str]
    assessed_by: str
    assessed_at: str


class PublicationGate(TypedDict):
    status: str
    reasons: List[str]
    approved_by: Optional[str]
    approved_at: Optional[str]


class RevisionMetadata(TypedDict):
    number: int
    action: str
    change_summary: str
    reason: Optional[str]
    changed_by: str
    compared_to_sha256: Optional[str]


class ReviewDecision(TypedDict):
    id: str
    type: str
    actor: str
    reason: Optional[str]
    notes: Optional[str]
    occurred_at: str


class ReviewComment(TypedDict):
    id: str
    actor: str
    body: str
    visibility: str
    occurred_at: str


class ReviewWorkflow(TypedDict):
    schema_version: str
    state: str
    priority: str
    assigned_reviewers: List[str]
    quality: ReviewQualityAssessment
    publication_gate: PublicationGate
    revision: RevisionMetadata
    decisions: List[ReviewDecision]
    comments: List[ReviewComment]


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
        "indicator_governance": IndicatorGovernance,
        "observation_lineage": ObservationLineage,
        "review_workflow": ReviewWorkflow,
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
