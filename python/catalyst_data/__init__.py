"""Catalyst Data canonical records and persistent repository services."""

from ._version import __version__
from .database import DatabaseConfigurationError, DatabaseHealth, DatabaseTarget, backend_name, database_url_from_env, resolve_database_target
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
from .handoff import HANDOFF_CONTRACT, HandoffValidationError, create_handoff, handoff_schema, validate_handoff
from .public_api import ApiRegistry, CatalystApiServer, openapi_document, public_projection, serve
from .connectors import (
    CONNECTOR_CONTRACT, ConnectorError, ConnectorFetchError, ConnectorRateLimited,
    ConnectorService, ConnectorValidationError, connector_schema, map_source_row,
    normalize_connector_definition, schema_fingerprint,
)
from .adapters import (
    ADAPTER_FRAMEWORK, AdapterError, AdapterManifest, AdapterRegistry, AdapterRunner,
    AdapterValidationError, GenericHttpAdapter, SourceAdapter, default_adapter_registry,
)
from .analysis_artifacts import (
    ANALYSIS_SCHEMA_VERSION, PACKAGE_SCHEMA_VERSION, AnalysisArtifactError,
    AnalysisArtifactService, normalize_analysis_definition,
)
from .platform import PLATFORM_SCHEMA_VERSION, PlatformError, PlatformService, platform_schema
from .migrations import MigrationError, MigrationManager, discover_migrations
from .repository import CatalystRepository, RepositoryError
from .storage_migration import StorageMigrationError, migrate_sqlite_to_postgresql
from .service import CatalystDataService
from .validation import RecordValidationError, jsonschema_available, schema, validate_record
from .us_public_data import USPublicDataError, USPublicDataService
from .dataset_catalog import DatasetCatalogError, DatasetCatalogService
from .entity_resolution import EntityResolutionError, EntityResolutionService
from .connected_graph import ConnectedGraphError, ConnectedGraphService

__all__ = [
    "__version__", "CatalystDataService", "CatalystRepository", "DatabaseHealth", "DatabaseTarget", "DatabaseConfigurationError",
    "backend_name", "database_url_from_env", "resolve_database_target", "StorageMigrationError", "migrate_sqlite_to_postgresql",
    "ImportPipelineError", "ImportService", "ImportSummary", "MigrationError", "MigrationManager",
    "RecordValidationError", "RepositoryError", "brief_markdown", "build_record", "classify_record",
    "compare_governance", "convert_value", "normalize_indicator_governance", "validate_indicator_governance",
    "normalize_observation_lineage", "validate_observation_lineage",
    "append_comment", "append_decision", "derive_quality", "normalize_review_workflow", "validate_review_workflow",
    "QueryStudio", "apply_query", "comparison_rows", "normalize_query_definition", "query_summary", "query_warnings",
    "HANDOFF_CONTRACT", "HandoffValidationError", "create_handoff", "handoff_schema", "validate_handoff",
    "ApiRegistry", "CatalystApiServer", "openapi_document", "public_projection", "serve",
    "CONNECTOR_CONTRACT", "ConnectorError", "ConnectorFetchError", "ConnectorRateLimited",
    "ConnectorService", "ConnectorValidationError", "connector_schema", "map_source_row",
    "normalize_connector_definition", "schema_fingerprint",
    "ADAPTER_FRAMEWORK", "AdapterError", "AdapterManifest", "AdapterRegistry", "AdapterRunner",
    "AdapterValidationError", "GenericHttpAdapter", "SourceAdapter", "default_adapter_registry",
    "PLATFORM_SCHEMA_VERSION", "PlatformError", "PlatformService", "platform_schema",
    "ANALYSIS_SCHEMA_VERSION", "PACKAGE_SCHEMA_VERSION", "AnalysisArtifactError",
    "AnalysisArtifactService", "normalize_analysis_definition",
    "classify_review", "classify_signal", "convert_legacy_record", "discover_migrations",
    "export_repository", "is_canonical_record", "jsonschema_available", "percent_change", "schema",
    "USPublicDataError", "USPublicDataService", "DatasetCatalogError", "DatasetCatalogService", "EntityResolutionService", "EntityResolutionError", "ConnectedGraphService", "ConnectedGraphError",
    "stable_id", "validate_payload", "validate_record", "validate_record_semantics",
]
