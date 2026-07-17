from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "catalyst_data.cli", *map(str, args)],
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "python")},
        capture_output=True,
        text=True,
    )


def test_brief_command_writes_canonical_outputs(tmp_path):
    markdown = tmp_path / "brief.md"
    result = run_cli("brief", ROOT / "examples/sample_project.json", markdown)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(markdown.with_suffix(".json").read_text(encoding="utf-8"))
    assert record["schema_version"] == "catalyst-data-record/1.0"
    assert markdown.exists()


def test_validate_command_accepts_canonical_output():
    result = run_cli("validate", ROOT / "outputs/sample_export.json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "valid" in result.stdout


def test_upgrade_command_converts_legacy_record(tmp_path):
    output = tmp_path / "upgraded.json"
    result = run_cli("upgrade", ROOT / "examples/sample_legacy_v1_0_record.json", output)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["producer"]["component"] == "migration-tool"
    assert record["schema_version"] == "catalyst-data-record/1.0"


def test_validate_command_rejects_legacy_record():
    result = run_cli("validate", ROOT / "examples/sample_legacy_v1_0_record.json")
    assert result.returncode == 1
    assert "ERROR" in result.stdout


def test_legacy_two_argument_cli_is_preserved(tmp_path):
    markdown = tmp_path / "legacy-command.md"
    result = run_cli(ROOT / "examples/sample_project.json", markdown)
    assert result.returncode == 0, result.stdout + result.stderr
    assert markdown.with_suffix(".json").exists()
