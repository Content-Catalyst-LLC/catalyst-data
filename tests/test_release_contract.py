from pathlib import Path
import json
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import __version__, schema


def test_versions_and_contract_are_synchronized():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert version == "2.7.0"
    assert __version__ == version
    manifest = json.loads((ROOT / "catalyst_data_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == version
    assert manifest["record_contract"] == "catalyst-data-record/1.0"
    php = (ROOT / "wordpress/sustainable-catalyst-data/sustainable-catalyst-data.php").read_text(encoding="utf-8")
    assert f"Version: {version}" in php
    assert f"SUSTAINABLE_CATALYST_DATA_VERSION', '{version}'" in php


def test_packaged_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_record_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_record_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    assert json.loads(canonical.read_text(encoding="utf-8")) == schema()




def test_packaged_evidence_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_evidence_chain_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_evidence_chain_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-evidence-chain/1.0"


def test_packaged_indicator_governance_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_indicator_governance_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_indicator_governance_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-indicator-governance/1.0"



def test_packaged_observation_lineage_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_observation_lineage_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_observation_lineage_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-observation-lineage/1.0"


def test_packaged_review_workflow_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_review_workflow_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_review_workflow_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-review-workflow/1.0"

def test_packaged_query_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_query_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_query_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-query/1.0"


def test_packaged_handoff_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_handoff_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_handoff_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-handoff/1.0"




def test_packaged_access_governance_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_access_governance_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_access_governance_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-access-governance/1.0"




def test_packaged_connector_operations_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_connector_operations_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_connector_operations_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-connector-operations/1.0"


def test_packaged_analysis_artifact_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_analysis_artifact_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_analysis_artifact_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-analysis-artifact/1.0"



def test_packaged_operational_hardening_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_operational_hardening_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_operational_hardening_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-operational-hardening/1.0"

def test_packaged_platform_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_platform_2_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_platform_2_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-platform/2.0"


def test_packaged_source_adapter_schema_matches_canonical_schema():
    canonical = ROOT / "schemas/catalyst_data_source_adapter_1_0.schema.json"
    packaged = ROOT / "python/catalyst_data/schemas/catalyst_data_source_adapter_1_0.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload["properties"]["schema_version"]["const"] == "catalyst-data-source-adapter/1.0"


def test_plugin_distribution_contains_wordpress_integration_assets():
    with zipfile.ZipFile(ROOT / "dist/sustainable-catalyst-data.zip") as archive:
        names = set(archive.namelist())
    assert "sustainable-catalyst-data/assets/catalyst-data-contract.js" in names
    assert "sustainable-catalyst-data/assets/catalyst-data-record-contract.js" in names
    assert "sustainable-catalyst-data/sustainable-catalyst-data.php" in names
    assert "sustainable-catalyst-data/assets/sustainable-catalyst-data.js" in names
    assert "sustainable-catalyst-data/assets/sustainable-catalyst-data.css" in names



def test_wordpress_integration_has_safe_public_proxy_and_accessible_controls():
    php = (ROOT / "wordpress/sustainable-catalyst-data/sustainable-catalyst-data.php").read_text(encoding="utf-8")
    javascript = (ROOT / "wordpress/sustainable-catalyst-data/assets/sustainable-catalyst-data.js").read_text(encoding="utf-8")
    css = (ROOT / "wordpress/sustainable-catalyst-data/assets/sustainable-catalyst-data.css").read_text(encoding="utf-8")
    assert "wp_safe_remote_get" in php
    assert "limit_response_size" in php
    assert "permission_callback" in php
    assert "sustainable_catalyst_data" in php
    assert "catalyst_data_status" in php
    assert "catalyst_data_archive_search" in php
    assert "catalyst_data_wayback" in php
    assert "catalyst_data_statistics" in php
    assert "/v1/archive/items" in php
    assert "/v1/wayback/captures" in php
    assert "/v1/statistics/status" in php
    assert "/v1/statistics/world-bank/observations" in php
    assert "/v1/statistics/un-sdg/observations" in php
    assert "archive.org/advancedsearch" not in php
    assert "api.worldbank.org" not in php
    assert "unstats.un.org/SDGAPI" not in php
    assert "web.archive.org/cdx" not in php
    assert "DATABASE_URL" not in php
    assert "Authorization: Bearer" not in php
    assert 'aria-busy="true"' in php
    assert "data-scd-retry" in php
    assert "fetch(" in javascript
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css


def test_release_documentation_exists():
    assert (ROOT / "release/v2.7.0.md").exists()
    assert (ROOT / "docs/data-contract.md").exists()
    assert (ROOT / "docs/migration-v1.0.md").exists()
    assert (ROOT / "docs/extension-rules.md").exists()
    assert (ROOT / "docs/evidence-chain.md").exists()
    assert (ROOT / "docs/source-versioning.md").exists()
    assert (ROOT / "docs/indicator-governance.md").exists()
    assert (ROOT / "docs/units-and-methodologies.md").exists()
    assert (ROOT / "docs/observation-lineage.md").exists()
    assert (ROOT / "docs/review-quality-revision.md").exists()
    assert (ROOT / "docs/query-comparison-export-studio.md").exists()
    assert (ROOT / "docs/public-api-embeds-handoffs.md").exists()
    assert (ROOT / "docs/institutional-workspaces-access-governance.md").exists()
    assert (ROOT / "docs/connectors-refresh-data-operations.md").exists()
    assert (ROOT / "docs/analysis-artifacts-reproducible-packages.md").exists()
    assert (ROOT / "docs/operational-hardening.md").exists()
    assert (ROOT / "docs/internet-archive-wayback-intelligence.md").exists()
    assert (ROOT / "docs/global-statistics-connector-pack.md").exists()
    assert (ROOT / "docs/backup-restore-recovery.md").exists()
    assert (ROOT / "docs/accessibility-offline-performance.md").exists()
    assert (ROOT / "docs/connected-evidence-measurement-platform.md").exists()
    assert (ROOT / "docs/postgresql-production-persistence.md").exists()
    assert (ROOT / "docs/external-source-adapter-framework.md").exists()
    assert (ROOT / "docs/wordpress-plugin.md").exists()
    assert (ROOT / "openapi/catalyst-data-openapi.json").exists()

def test_release_check_isolates_stale_bytecode_before_package_import() -> None:
    source = (ROOT / "scripts/check_release.py").read_text(encoding="utf-8")
    cache_guard = source.index("sys.pycache_prefix")
    package_import = source.index("from catalyst_data import")
    assert cache_guard < package_import
    assert 'ROOT.rglob("__pycache__")' in source
    assert "sys.dont_write_bytecode = True" in source


def test_python_package_declares_migration_resources():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"migrations/*.sql"' in pyproject
    assert '"postgresql/*.sql"' in pyproject
    migrations = sorted((ROOT / "python/catalyst_data/migrations").glob("*.sql"))
    assert [path.name for path in migrations] == [
        "001_core_schema.down.sql",
        "001_core_schema.up.sql",
        "002_persistent_repository.down.sql",
        "002_persistent_repository.up.sql",
        "003_sources_provenance_evidence.down.sql",
        "003_sources_provenance_evidence.up.sql",
        "004_indicator_units_methodology.down.sql",
        "004_indicator_units_methodology.up.sql",
        "005_questions_instruments_datasets_observations.down.sql",
        "005_questions_instruments_datasets_observations.up.sql",
        "006_review_quality_revision_workflow.down.sql",
        "006_review_quality_revision_workflow.up.sql",
        "007_query_comparison_export_studio.down.sql",
        "007_query_comparison_export_studio.up.sql",
        "008_public_api_embeds_handoffs.down.sql",
        "008_public_api_embeds_handoffs.up.sql",
        "009_institutional_workspaces_access_governance.down.sql",
        "009_institutional_workspaces_access_governance.up.sql",
        "010_connectors_refresh_data_operations.down.sql",
        "010_connectors_refresh_data_operations.up.sql",
        "011_analysis_artifacts_reproducible_packages.down.sql",
        "011_analysis_artifacts_reproducible_packages.up.sql",
        "012_accessibility_offline_performance_hardening.down.sql",
        "012_accessibility_offline_performance_hardening.up.sql",
        "013_connected_evidence_measurement_platform.down.sql",
        "013_connected_evidence_measurement_platform.up.sql",
        "014_postgresql_storage_abstraction.down.sql",
        "014_postgresql_storage_abstraction.up.sql",
        "015_external_source_adapter_wordpress_foundation.down.sql",
        "015_external_source_adapter_wordpress_foundation.up.sql",
        "016_internet_archive_wayback_intelligence.down.sql",
        "016_internet_archive_wayback_intelligence.up.sql",
        "017_global_statistics_connector_pack.down.sql",
        "017_global_statistics_connector_pack.up.sql",
        "018_us_public_data_connector_pack.down.sql",
        "018_us_public_data_connector_pack.up.sql",
        "019_earth_climate_ocean_data_network.down.sql",
        "019_earth_climate_ocean_data_network.up.sql",
        "020_space_scientific_data_network.down.sql",
        "020_space_scientific_data_network.up.sql",
    ]
