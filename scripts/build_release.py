#!/usr/bin/env python3
"""Build deterministic Catalyst Data distribution artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = ROOT / "wordpress" / "catalyst-data-demo"
PLUGIN_ZIP = ROOT / "dist" / "catalyst-data-demo.zip"
FIXED_TIME = (2026, 7, 16, 12, 0, 0)
FIXED_DATETIME = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import convert_legacy_record


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def deterministic_zip(source: Path, destination: Path, root_name: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        directories = {root_name}
        files: list[tuple[Path, str]] = []
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source).as_posix()
            arcname = f"{root_name}/{relative}"
            if path.is_dir():
                directories.add(arcname)
            else:
                files.append((path, arcname))
                parent = Path(arcname).parent
                while str(parent) not in (".", ""):
                    directories.add(parent.as_posix())
                    parent = parent.parent
        for directory in sorted(directories):
            info = zipfile.ZipInfo(directory.rstrip("/") + "/", FIXED_TIME)
            info.create_system = 3
            info.external_attr = (0o755 << 16) | 0x10
            archive.writestr(info, b"")
        for path, arcname in files:
            info = zipfile.ZipInfo(arcname, FIXED_TIME)
            info.create_system = 3
            mode = 0o755 if os.access(path, os.X_OK) else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(destination)


def regenerate_examples() -> None:
    run(sys.executable, "python/generate_data_brief.py", "examples/sample_project.json", "outputs/generated_brief.md")
    shutil.copyfile(ROOT / "outputs" / "generated_brief.json", ROOT / "outputs" / "sample_export.json")
    shutil.copyfile(ROOT / "outputs" / "generated_brief.md", ROOT / "outputs" / "sample_catalyst_data_brief.md")

    legacy = json.loads((ROOT / "examples/sample_legacy_v1_0_record.json").read_text(encoding="utf-8"))
    upgraded = convert_legacy_record(legacy, now=FIXED_DATETIME)
    (ROOT / "outputs/upgraded_legacy_record.json").write_text(
        json.dumps(upgraded, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify outputs after rebuilding")
    args = parser.parse_args()

    run(sys.executable, "scripts/sync_contract.py")
    run(sys.executable, "scripts/sync_record_contract.py")
    regenerate_examples()
    deterministic_zip(PLUGIN_SOURCE, PLUGIN_ZIP, "catalyst-data-demo")

    print(f"built {PLUGIN_ZIP.relative_to(ROOT)}")
    print(f"sha256 {checksum(PLUGIN_ZIP)}")
    if args.check:
        # Replace this process and run the dependency-light build verification.
        # The full source matrix remains available through scripts/check_release.py;
        # avoiding nested pytest/CLI subprocesses keeps deterministic packaging
        # reliable in constrained CI and installer environments.
        os.execv(
            sys.executable,
            [
                sys.executable,
                str(ROOT / "scripts/check_release.py"),
                "--portable",
                "--skip-build-check",
            ],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
