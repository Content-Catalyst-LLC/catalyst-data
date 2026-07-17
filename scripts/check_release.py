#!/usr/bin/env python3
"""Validate the Catalyst Data release and package contract."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Release archives normalize source timestamps for reproducibility. When an
# older checkout contains bytecode generated from a same-length version file,
# CPython can otherwise accept that stale cache after an in-place upgrade.
# Remove local bytecode and route this process away from repository caches
# before importing the package. Child checks will then compile clean sources.
for cache_dir in ROOT.rglob("__pycache__"):
    shutil.rmtree(cache_dir, ignore_errors=True)
for bytecode_file in list(ROOT.rglob("*.pyc")) + list(ROOT.rglob("*.pyo")):
    try:
        bytecode_file.unlink()
    except FileNotFoundError:
        pass
sys.dont_write_bytecode = True
sys.pycache_prefix = str(ROOT / ".release-check-pycache")
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import (
    __version__,
    build_record,
    classify_review,
    classify_signal,
    convert_legacy_record,
    schema,
    validate_record,
    validate_record_semantics,
    CatalystRepository,
    ImportService,
    discover_migrations,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


def fail(message: str) -> None:
    raise RuntimeError(message)


def command(args: list[str], required: bool = True, env: dict[str, str] | None = None) -> None:
    executable = shutil.which(args[0])
    if not executable:
        if required:
            fail(f"Required command not found: {args[0]}")
        print(f"SKIP: {args[0]} is not installed")
        return
    print("RUN:", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True, timeout=180, env=env)


def validate_versions() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"Invalid VERSION: {version!r}")
    if version != "1.6.0":
        fail("Unexpected release version")
    manifest = json.loads((ROOT / "catalyst_data_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version or manifest.get("record_contract") != "catalyst-data-record/1.0":
        fail("Manifest does not match VERSION and record contract")
    if __version__ != version:
        fail("Python package version does not match VERSION")
    php = (ROOT / "wordpress/catalyst-data-demo/catalyst-data-demo.php").read_text(encoding="utf-8")
    if f"Version: {version}" not in php or f"CATALYST_DATA_DEMO_VERSION', '{version}'" not in php:
        fail("WordPress version does not match VERSION")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version}" not in changelog:
        fail("CHANGELOG does not contain the release version")
    if not (ROOT / f"release/v{version}.md").exists():
        fail("Release notes are missing")
    return version


def validate_schemas() -> None:
    canonical_path = ROOT / "schemas/catalyst_data_record_1_0.schema.json"
    package_path = ROOT / "python/catalyst_data/schemas/catalyst_data_record_1_0.schema.json"
    if canonical_path.read_bytes() != package_path.read_bytes():
        fail("Packaged record schema differs from canonical schema")
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    if canonical != schema():
        fail("Runtime schema loader differs from canonical schema")
    evidence_path = ROOT / "schemas/catalyst_data_evidence_chain_1_0.schema.json"
    evidence_package = ROOT / "python/catalyst_data/schemas/catalyst_data_evidence_chain_1_0.schema.json"
    if evidence_path.read_bytes() != evidence_package.read_bytes():
        fail("Packaged evidence-chain schema differs from canonical schema")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("properties", {}).get("schema_version", {}).get("const") != "catalyst-data-evidence-chain/1.0":
        fail("Evidence-chain schema identifier is invalid")
    governance_path = ROOT / "schemas/catalyst_data_indicator_governance_1_0.schema.json"
    governance_package = ROOT / "python/catalyst_data/schemas/catalyst_data_indicator_governance_1_0.schema.json"
    if governance_path.read_bytes() != governance_package.read_bytes():
        fail("Packaged indicator-governance schema differs from canonical schema")
    governance = json.loads(governance_path.read_text(encoding="utf-8"))
    if governance.get("properties", {}).get("schema_version", {}).get("const") != "catalyst-data-indicator-governance/1.0":
        fail("Indicator-governance schema identifier is invalid")
    lineage_path = ROOT / "schemas/catalyst_data_observation_lineage_1_0.schema.json"
    lineage_package = ROOT / "python/catalyst_data/schemas/catalyst_data_observation_lineage_1_0.schema.json"
    if lineage_path.read_bytes() != lineage_package.read_bytes():
        fail("Packaged observation-lineage schema differs from canonical schema")
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    if lineage.get("properties", {}).get("schema_version", {}).get("const") != "catalyst-data-observation-lineage/1.0":
        fail("Observation-lineage schema identifier is invalid")
    workflow_path = ROOT / "schemas/catalyst_data_review_workflow_1_0.schema.json"
    workflow_package = ROOT / "python/catalyst_data/schemas/catalyst_data_review_workflow_1_0.schema.json"
    if workflow_path.read_bytes() != workflow_package.read_bytes():
        fail("Packaged review-workflow schema differs from canonical schema")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    if workflow.get("properties", {}).get("schema_version", {}).get("const") != "catalyst-data-review-workflow/1.0":
        fail("Review-workflow schema identifier is invalid")
    if canonical.get("$id") != "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json":
        fail("Canonical record schema ID is invalid")
    if Draft202012Validator is not None:
        Draft202012Validator.check_schema(canonical)
        export = json.loads((ROOT / "schemas/catalyst_data_export.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(export)
        Draft202012Validator.check_schema(evidence)
        Draft202012Validator.check_schema(governance)
        Draft202012Validator.check_schema(lineage)
        Draft202012Validator.check_schema(workflow)
    else:
        print("INFO: jsonschema unavailable; runtime fallback validation remains active")


def validate_json_files() -> None:
    for path in sorted(ROOT.rglob("*.json")):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        json.loads(path.read_text(encoding="utf-8"))

    for name in (
        "outputs/generated_brief.json",
        "outputs/sample_export.json",
        "outputs/upgraded_legacy_record.json",
    ):
        record = json.loads((ROOT / name).read_text(encoding="utf-8"))
        validate_record(record)
        validate_record_semantics(record)

    sample_input = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    rebuilt = build_record(sample_input)
    saved = json.loads((ROOT / "outputs/generated_brief.json").read_text(encoding="utf-8"))
    if rebuilt != saved:
        fail("Generated sample export is stale")

    legacy = json.loads((ROOT / "examples/sample_legacy_v1_0_record.json").read_text(encoding="utf-8"))
    upgraded = convert_legacy_record(legacy, now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc))
    saved_upgrade = json.loads((ROOT / "outputs/upgraded_legacy_record.json").read_text(encoding="utf-8"))
    if upgraded != saved_upgrade:
        fail("Legacy upgrade fixture is stale")


def validate_sql() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    connection.executescript((ROOT / "queries.sql").read_text(encoding="utf-8"))
    rows = connection.execute(
        "SELECT confidence, source, direction, review_status, signal_status, percent_change FROM measurement_review ORDER BY measurement_id"
    ).fetchall()
    if len(rows) != 2:
        fail(f"Expected 2 seeded measurements, found {len(rows)}")
    for confidence, source_name, direction, review_status, signal_status, change in rows:
        if review_status != classify_review(confidence, source_name):
            fail("SQL and Python review status disagree")
        if signal_status != classify_signal(change, direction):
            fail("SQL and Python signal status disagree")
    connection.close()


def validate_repository_pipeline() -> None:
    migrations = discover_migrations()
    if [migration.version for migration in migrations] != [1, 2, 3, 4, 5, 6]:
        fail("Expected contiguous migrations 1 through 6")
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "catalyst-data.sqlite3"
        repository = CatalystRepository(database)
        if repository.initialize() != [1, 2, 3, 4, 5, 6]:
            fail("Fresh repository did not apply migrations 1 through 6")
        if not repository.health().healthy:
            fail("Fresh repository health check failed")
        if repository.rollback(1) != [6]:
            fail("Migration 6 rollback failed")
        if repository.migrate() != [6]:
            fail("Migration 6 reapplication failed")
        service = ImportService(repository)
        source = ROOT / "examples/imports/records.json"
        dry_run = service.run(source, dry_run=True)
        if dry_run.inserted != 2 or not dry_run.rolled_back or repository.stats()["records"] != 0:
            fail("Dry-run import did not roll back cleanly")
        imported = service.run(source)
        if imported.inserted != 2 or imported.failed:
            fail("JSON import failed")
        repeated = service.run(source)
        if repeated.skipped != 2 or repository.stats()["records"] != 2:
            fail("Idempotent import contract failed")
        stats = repository.stats()
        if stats["source_versions"] < 2 or stats["record_revisions"] != 2 or stats["provenance_events"] < 6:
            fail("Evidence history was not persisted")
        if stats["indicator_versions"] < 2 or stats["methodology_versions"] < 2 or stats["units"] < 1:
            fail("Indicator governance history was not persisted")
        if stats["questions"] < 2 or stats["instruments"] < 2 or stats["datasets"] < 2 or stats["observations"] < 2:
            fail("Observation lineage was not persisted")
        if stats["review_cases"] != 2 or stats["quality_assessments"] != 2 or stats["revision_diffs"] != 2:
            fail("Review workflow was not persisted")
        first = repository.list_records(limit=1)[0]
        indicator_id = first["indicator"]["id"]
        if not repository.indicator_registry(indicator_id):
            fail("Indicator registry inspection failed")
        if not repository.methodology_history(first["indicator_governance"]["methodology"]["id"]):
            fail("Methodology history inspection failed")
        unit_id = first["indicator_governance"]["unit"]["id"]
        if repository.convert(12, unit_id, unit_id) != 12:
            fail("Governed unit conversion failed")
        if repository.compare(first["record_id"], first["record_id"])["status"] != "equivalent":
            fail("Governed comparability check failed")
        first_record = repository.list_records(limit=1)[0]
        evidence_payload = repository.evidence(first_record["record_id"])
        if not evidence_payload or not evidence_payload["chain"] or not evidence_payload["provenance"]:
            fail("Evidence-chain inspection failed")
        lineage_payload = repository.lineage(first_record["record_id"])
        if not lineage_payload or not lineage_payload["lineage"] or not lineage_payload["events"]:
            fail("Observation-lineage inspection failed")
        record_id = first_record["record_id"]
        repository.assign_review(record_id, "reviewer@example.org", "author@example.org")
        repository.submit_review(record_id, "author@example.org", "Ready for independent review")
        repository.start_review(record_id, "reviewer@example.org")
        repository.decide_review(record_id, "approved", "reviewer@example.org", reason="Evidence and method are sufficient")
        review_payload = repository.review_history(record_id)
        if not review_payload or not review_payload["decisions"] or not review_payload["approval_snapshots"]:
            fail("Review history or approval snapshot persistence failed")
        if repository.get_record(record_id)["review_workflow"]["publication_gate"]["status"] != "external":
            fail("Approved record did not receive an external publication gate")
        from catalyst_data.exporter import export_repository
        json_export = Path(directory) / "export.json"
        csv_export = Path(directory) / "export.csv"
        if export_repository(repository, json_export, format_name="json") != 2:
            fail("JSON repository export failed")
        if export_repository(repository, csv_export, format_name="csv") != 2:
            fail("CSV repository export failed")
        payload = json.loads(json_export.read_text(encoding="utf-8"))
        if payload.get("record_count") != 2:
            fail("Repository export count is invalid")


def validate_python_metadata() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for required in (
        'dependencies = ["jsonschema>=4.21"]',
        'catalyst-data = "catalyst_data.cli:main"',
        'catalyst_data = ["schemas/*.json", "migrations/*.sql"]',
    ):
        if required not in pyproject:
            fail(f"pyproject metadata is missing: {required}")
    if not (ROOT / "python/catalyst_data/types.py").exists():
        fail("Typed record mappings are missing")
    if not (ROOT / "python/catalyst_data/schemas/catalyst_data_evidence_chain_1_0.schema.json").exists():
        fail("Packaged evidence-chain schema is missing")
    if not (ROOT / "python/catalyst_data/schemas/catalyst_data_indicator_governance_1_0.schema.json").exists():
        fail("Packaged indicator-governance schema is missing")
    if not (ROOT / "python/catalyst_data/schemas/catalyst_data_observation_lineage_1_0.schema.json").exists():
        fail("Packaged observation-lineage schema is missing")
    if not (ROOT / "python/catalyst_data/schemas/catalyst_data_review_workflow_1_0.schema.json").exists():
        fail("Packaged review-workflow schema is missing")


def validate_plugin_zip(skip_build_check: bool) -> None:
    path = ROOT / "dist/catalyst-data-demo.zip"
    if not path.exists():
        fail("WordPress distribution ZIP is missing")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {
            "catalyst-data-demo/catalyst-data-demo.php",
            "catalyst-data-demo/assets/catalyst-data-demo.js",
            "catalyst-data-demo/assets/catalyst-data-contract.js",
            "catalyst-data-demo/assets/catalyst-data-record-contract.js",
            "catalyst-data-demo/assets/catalyst-data-demo.css",
            "catalyst-data-demo/README.md",
        }
        missing = required - names
        if missing:
            fail(f"WordPress ZIP is missing: {', '.join(sorted(missing))}")
    if skip_build_check:
        return
    original = path.read_bytes()
    spec = importlib.util.spec_from_file_location("catalyst_data_build_release", ROOT / "scripts/build_release.py")
    if spec is None or spec.loader is None:
        fail("Unable to load deterministic release builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "catalyst-data-demo.zip"
        module.deterministic_zip(ROOT / "wordpress/catalyst-data-demo", candidate, "catalyst-data-demo")
        rebuilt = candidate.read_bytes()
    if hashlib.sha256(original).digest() != hashlib.sha256(rebuilt).digest():
        fail("WordPress ZIP is not reproducible or was stale")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build-check", action="store_true")
    parser.add_argument("--portable", action="store_true", help="run dependency-light smoke checks for installer environments")
    parser.add_argument("--skip-compile", action="store_true", help="skip compileall when the caller already ran the full source suite")
    args = parser.parse_args()

    print("STEP: versions", flush=True)
    version = validate_versions()
    print("STEP: generated contracts", flush=True)
    command([sys.executable, "scripts/sync_contract.py", "--check"])
    command([sys.executable, "scripts/sync_record_contract.py", "--check"])
    print("STEP: compile and portable smoke suite", flush=True)
    if args.skip_compile:
        print("INFO: compileall already covered by the calling release suite")
    else:
        command([sys.executable, "-m", "compileall", "-q", "python", "scripts", "tests"])
    # Run the dependency-light child process before pytest and repository
    # validation initialize process-global schema and SQLite state. This keeps
    # the full validator as reliable as the portable installer path.
    command([sys.executable, "scripts/smoke_test.py"])
    if args.portable:
        print("INFO: portable mode skips the full pytest matrix")
    else:
        print("INFO: run scripts/test_release.sh for the complete pytest and syntax matrix")
    print("STEP: schemas", flush=True)
    validate_schemas()
    print("STEP: JSON records", flush=True)
    validate_json_files()
    print("STEP: SQL parity", flush=True)
    validate_sql()
    print("STEP: repository migrations, review, lineage, governance, evidence, and imports", flush=True)
    validate_repository_pipeline()
    print("STEP: Python metadata", flush=True)
    validate_python_metadata()
    print("STEP: browser and PHP", flush=True)
    if args.portable:
        print("INFO: portable mode skips optional Node and PHP checks")
    else:
        command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-contract.js"])
        command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-record-contract.js"])
        command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-demo.js"])
        command(["node", "scripts/test_browser_contract.js"])
        command(["php", "-l", "wordpress/catalyst-data-demo/catalyst-data-demo.php"])
    print("STEP: plugin package", flush=True)
    validate_plugin_zip(args.skip_build_check)
    print(f"Catalyst Data v{version} release contract passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, sqlite3.Error, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
