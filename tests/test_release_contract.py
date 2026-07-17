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
    assert version == "1.6.0"
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


def test_plugin_distribution_contains_both_contract_assets():
    with zipfile.ZipFile(ROOT / "dist/catalyst-data-demo.zip") as archive:
        names = set(archive.namelist())
    assert "catalyst-data-demo/assets/catalyst-data-contract.js" in names
    assert "catalyst-data-demo/assets/catalyst-data-record-contract.js" in names
    assert "catalyst-data-demo/catalyst-data-demo.php" in names


def test_release_documentation_exists():
    assert (ROOT / "release/v1.6.0.md").exists()
    assert (ROOT / "docs/data-contract.md").exists()
    assert (ROOT / "docs/migration-v1.0.md").exists()
    assert (ROOT / "docs/extension-rules.md").exists()
    assert (ROOT / "docs/evidence-chain.md").exists()
    assert (ROOT / "docs/source-versioning.md").exists()
    assert (ROOT / "docs/indicator-governance.md").exists()
    assert (ROOT / "docs/units-and-methodologies.md").exists()
    assert (ROOT / "docs/observation-lineage.md").exists()
    assert (ROOT / "docs/review-quality-revision.md").exists()

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
    ]
