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


def test_repository_cli_workflow(tmp_path):
    database = tmp_path / "repository.db"
    source = tmp_path / "records.json"
    source.write_text(json.dumps({"records": [json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))]}), encoding="utf-8")
    result = run_cli("init", database)
    assert result.returncode == 0, result.stdout + result.stderr
    result = run_cli("import", database, source)
    assert result.returncode == 0, result.stdout + result.stderr
    result = run_cli("status", database, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads(result.stdout)
    assert status["healthy"] is True
    assert status["record_count"] == 1
    export = tmp_path / "export.json"
    result = run_cli("export", database, export)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(export.read_text(encoding="utf-8"))
    assert payload["record_count"] == 1
    result = run_cli("review", database)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Urban Tree Canopy Program" in result.stdout


def test_evidence_cli_commands_in_process(tmp_path, capsys):
    from catalyst_data.cli import main
    from catalyst_data.importer import ImportService
    from catalyst_data.repository import CatalystRepository

    database = tmp_path / "evidence.db"
    repository = CatalystRepository(database)
    source = tmp_path / "records.json"
    source.write_text(json.dumps({"records": [json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))]}), encoding="utf-8")
    ImportService(repository).run(source)
    record = repository.list_records(limit=1)[0]

    assert main(["sources", str(database), "--source-id", record["source"]["id"], "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "Internal program tracker" in output

    assert main(["provenance", str(database), record["record_id"]]) == 0
    output = capsys.readouterr().out
    assert "record_created" in output

    assert main(["evidence", str(database), record["record_id"]]) == 0
    output = capsys.readouterr().out
    assert "completeness_score" in output
