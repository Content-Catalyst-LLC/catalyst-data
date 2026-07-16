from pathlib import Path
import json
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import __version__


def test_versions_are_synchronized():
    version = (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert __version__ == version
    assert json.loads((ROOT / "catalyst_data_manifest.json").read_text())["version"] == version
    php = (ROOT / "wordpress/catalyst-data-demo/catalyst-data-demo.php").read_text()
    assert f"Version: {version}" in php
    assert f"CATALYST_DATA_DEMO_VERSION', '{version}'" in php


def test_plugin_distribution_contains_contract_asset():
    with zipfile.ZipFile(ROOT / "dist/catalyst-data-demo.zip") as archive:
        names = set(archive.namelist())
    assert "catalyst-data-demo/assets/catalyst-data-contract.js" in names
    assert "catalyst-data-demo/catalyst-data-demo.php" in names
