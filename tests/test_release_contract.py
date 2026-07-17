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
    assert version == "2.0.0"
    assert __version__ == version
    manifest = json.loads((ROOT / "catalyst_data_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == version
    assert manifest["record_contract"] == "catalyst-data-record/1.0"
    php = (ROOT / "wordpress/catalyst-data-demo/catalyst-data-demo.php").read_text(encoding="utf-8")
    assert f"Version: {version}" in php
    assert f"CATALYST_DATA_DEMO_VERSION', '{version}'" in php


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


def test_plugin_distribution_contains_both_contract_assets():
    with zipfile.ZipFile(ROOT / "dist/catalyst-data-demo.zip") as archive:
        names = set(archive.namelist())
    assert "catalyst-data-demo/assets/catalyst-data-contract.js" in names
    assert "catalyst-data-demo/assets/catalyst-data-record-contract.js" in names
    assert "catalyst-data-demo/catalyst-data-demo.php" in names
    assert "catalyst-data-demo/assets/catalyst-data-embed.js" in names



def test_wordpress_embed_has_accessible_offline_controls():
    php = (ROOT / "wordpress/catalyst-data-demo/catalyst-data-demo.php").read_text(encoding="utf-8")
    javascript = (ROOT / "wordpress/catalyst-data-demo/assets/catalyst-data-embed.js").read_text(encoding="utf-8")
    css = (ROOT / "wordpress/catalyst-data-demo/assets/catalyst-data-demo.css").read_text(encoding="utf-8")
    assert 'aria-busy="true"' in php
    assert 'aria-atomic="true"' in php
    assert 'data-cdata-embed-retry' in php
    assert "localStorage" in javascript
    assert "Offline fallback" in javascript
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css

def test_release_documentation_exists():
    assert (ROOT / "release/v2.0.0.md").exists()
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
    assert (ROOT / "docs/backup-restore-recovery.md").exists()
    assert (ROOT / "docs/accessibility-offline-performance.md").exists()
    assert (ROOT / "docs/connected-evidence-measurement-platform.md").exists()
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
    ]
