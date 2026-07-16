#!/usr/bin/env python3
"""Validate the Catalyst Data release and package contract."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # Installer environments may only have the standard library.
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import classify_review, classify_signal, percent_change


def fail(message: str) -> None:
    raise RuntimeError(message)


def command(args: list[str], required: bool = True) -> None:
    executable = shutil.which(args[0])
    if not executable:
        if required:
            fail(f"Required command not found: {args[0]}")
        print(f"SKIP: {args[0]} is not installed")
        return
    subprocess.run(args, cwd=ROOT, check=True)


def validate_versions() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"Invalid VERSION: {version!r}")
    manifest = json.loads((ROOT / "catalyst_data_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        fail("Manifest version does not match VERSION")
    from catalyst_data import __version__
    if __version__ != version:
        fail("Python package version does not match VERSION")
    php = (ROOT / "wordpress/catalyst-data-demo/catalyst-data-demo.php").read_text(encoding="utf-8")
    if f"Version: {version}" not in php or f"CATALYST_DATA_DEMO_VERSION', '{version}'" not in php:
        fail("WordPress version does not match VERSION")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version}" not in changelog:
        fail("CHANGELOG does not contain the release version")
    return version


def validate_export_shape(payload: dict, name: str) -> None:
    required = {
        "entity", "indicator", "period", "values", "source", "confidence",
        "review_status", "signal_status", "trace_path"
    }
    missing = required - set(payload)
    if missing:
        fail(f"{name} is missing fields: {', '.join(sorted(missing))}")
    if payload["review_status"] not in {"missing source", "needs evidence", "reviewable with caution", "reviewable"}:
        fail(f"{name} has an invalid review_status")
    if payload["signal_status"] not in {"indeterminate", "improving", "declining", "unchanged", "descriptive"}:
        fail(f"{name} has an invalid signal_status")
    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 100:
        fail(f"{name} has invalid confidence")
    percent = payload["values"].get("percent_change")
    if percent is not None and (not isinstance(percent, (int, float)) or isinstance(percent, bool)):
        fail(f"{name} has invalid percent_change")
    expected_trace = ["entity", "indicator", "period", "measurement", "source", "confidence", "review"]
    if payload["trace_path"] != expected_trace:
        fail(f"{name} has an invalid trace path")


def validate_json() -> None:
    for path in sorted(ROOT.rglob("*.json")):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/catalyst_data_export.schema.json").read_text(encoding="utf-8"))
    validator = None
    if Draft202012Validator is not None:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    else:
        print("INFO: jsonschema is unavailable; using built-in export contract checks")
    for name in ("outputs/generated_brief.json", "outputs/sample_export.json"):
        payload = json.loads((ROOT / name).read_text(encoding="utf-8"))
        validate_export_shape(payload, name)
        if validator is not None:
            errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
            if errors:
                fail(f"{name} does not validate: {errors[0].message}")


def validate_sql() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    connection.executescript((ROOT / "queries.sql").read_text(encoding="utf-8"))
    rows = connection.execute(
        "SELECT confidence, source, review_status, signal_status, percent_change FROM measurement_review ORDER BY measurement_id"
    ).fetchall()
    if len(rows) != 2:
        fail(f"Expected 2 seeded measurements, found {len(rows)}")
    for confidence, source, review_status, signal_status, change in rows:
        if review_status != classify_review(confidence, source):
            fail("SQL and Python review status disagree")
        direction = connection.execute(
            "SELECT direction FROM measurement_review WHERE confidence=? AND source=?",
            (confidence, source),
        ).fetchone()[0]
        if signal_status != classify_signal(change, direction):
            fail("SQL and Python signal status disagree")
    connection.close()


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
    parser.add_argument(
        "--portable",
        action="store_true",
        help="allow optional Node and PHP syntax checks to be skipped when unavailable",
    )
    args = parser.parse_args()
    version = validate_versions()
    command([sys.executable, "scripts/sync_contract.py", "--check"])
    validate_json()
    validate_sql()
    command([sys.executable, "-m", "compileall", "-q", "python", "scripts", "tests"])
    command([sys.executable, "scripts/smoke_test.py"])
    if importlib.util.find_spec("pytest") is not None:
        command([sys.executable, "-m", "pytest", "-q"])
    else:
        print("INFO: pytest is unavailable; standard-library smoke tests completed")
    command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-contract.js"], required=not args.portable)
    command(["node", "--check", "wordpress/catalyst-data-demo/assets/catalyst-data-demo.js"], required=not args.portable)
    command(["node", "scripts/test_browser_contract.js"], required=not args.portable)
    command(["php", "-l", "wordpress/catalyst-data-demo/catalyst-data-demo.php"], required=not args.portable)
    validate_plugin_zip(args.skip_build_check)
    print(f"Catalyst Data v{version} release contract passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
