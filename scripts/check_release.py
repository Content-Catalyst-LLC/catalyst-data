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
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    if version != "1.1.0":
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
    if canonical.get("$id") != "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json":
        fail("Canonical record schema ID is invalid")
    if Draft202012Validator is not None:
        Draft202012Validator.check_schema(canonical)
        export = json.loads((ROOT / "schemas/catalyst_data_export.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(export)
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


def validate_python_metadata() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for required in (
        'dependencies = ["jsonschema>=4.21"]',
        'catalyst-data = "catalyst_data.cli:main"',
        'catalyst_data = ["schemas/*.json"]',
    ):
        if required not in pyproject:
            fail(f"pyproject metadata is missing: {required}")
    if not (ROOT / "python/catalyst_data/types.py").exists():
        fail("Typed record mappings are missing")


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
    command([sys.executable, "scripts/build_release.py"])
    rebuilt = path.read_bytes()
    if hashlib.sha256(original).digest() != hashlib.sha256(rebuilt).digest():
        fail("WordPress ZIP is not reproducible or was stale")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build-check", action="store_true")
    parser.add_argument("--portable", action="store_true", help="skip optional Node and PHP checks when unavailable")
    args = parser.parse_args()

    print("STEP: versions", flush=True)
    version = validate_versions()
    print("STEP: generated contracts", flush=True)
    command([sys.executable, "scripts/sync_contract.py", "--check"])
    command([sys.executable, "scripts/sync_record_contract.py", "--check"])
    print("STEP: schemas", flush=True)
    validate_schemas()
    print("STEP: JSON records", flush=True)
    validate_json_files()
    print("STEP: SQL parity", flush=True)
    validate_sql()
    print("STEP: Python metadata", flush=True)
    validate_python_metadata()
    print("STEP: compile and tests", flush=True)
    command([sys.executable, "-m", "compileall", "-q", "python", "scripts", "tests"])
    command([sys.executable, "scripts/smoke_test.py"])
    if importlib.util.find_spec("pytest") is not None:
        pytest_env = os.environ.copy()
        pytest_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        command([sys.executable, "-m", "pytest", "-q"], env=pytest_env)
    else:
        print("INFO: pytest unavailable; portable smoke tests completed")
    print("STEP: browser and PHP", flush=True)
    command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-contract.js"], required=not args.portable)
    command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-record-contract.js"], required=not args.portable)
    command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-demo.js"], required=not args.portable)
    command(["node", "scripts/test_browser_contract.js"], required=not args.portable)
    command(["php", "-l", "wordpress/catalyst-data-demo/catalyst-data-demo.php"], required=not args.portable)
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
