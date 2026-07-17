"""Catalyst Data canonical records and persistent repository services."""

from ._version import __version__
from .database import DatabaseHealth
from .engine import (
    brief_markdown,
    build_record,
    classify_record,
    classify_review,
    classify_signal,
    convert_legacy_record,
    is_canonical_record,
    percent_change,
    stable_id,
    validate_payload,
    validate_record_semantics,
)
from .exporter import export_repository
from .importer import ImportPipelineError, ImportService, ImportSummary
from .governance import compare_governance, convert_value, normalize_indicator_governance, validate_indicator_governance
from .lineage import normalize_observation_lineage, validate_observation_lineage
from .review import append_comment, append_decision, derive_quality, normalize_review_workflow, validate_review_workflow
from .query_studio import QueryStudio, apply_query, comparison_rows, normalize_query_definition, query_summary, query_warnings
from .migrations import MigrationError, MigrationManager, discover_migrations
from .repository import CatalystRepository, RepositoryError
from .service import CatalystDataService
from .validation import RecordValidationError, jsonschema_available, schema, validate_record

__all__ = [
    "__version__", "CatalystDataService", "CatalystRepository", "DatabaseHealth",
    "ImportPipelineError", "ImportService", "ImportSummary", "MigrationError", "MigrationManager",
    "RecordValidationError", "RepositoryError", "brief_markdown", "build_record", "classify_record",
    "compare_governance", "convert_value", "normalize_indicator_governance", "validate_indicator_governance",
    "normalize_observation_lineage", "validate_observation_lineage",
    "append_comment", "append_decision", "derive_quality", "normalize_review_workflow", "validate_review_workflow",
    "QueryStudio", "apply_query", "comparison_rows", "normalize_query_definition", "query_summary", "query_warnings",
    "classify_review", "classify_signal", "convert_legacy_record", "discover_migrations",
    "export_repository", "is_canonical_record", "jsonschema_available", "percent_change", "schema",
    "stable_id", "validate_payload", "validate_record", "validate_record_semantics",
]
