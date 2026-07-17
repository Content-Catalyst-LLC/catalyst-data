from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from catalyst_data.cli import main
from catalyst_data.importer import ImportService
from catalyst_data.platform import PLATFORM_SCHEMA_VERSION, PlatformService, platform_schema
from catalyst_data.public_api import ApiRegistry, CatalystApiServer
from catalyst_data.repository import CatalystRepository

ROOT = Path(__file__).resolve().parents[1]


def prepared(tmp_path: Path) -> tuple[CatalystRepository, PlatformService]:
    repository = CatalystRepository(tmp_path / "platform.sqlite3")
    assert repository.initialize() == list(range(1, 14))
    service = PlatformService(repository)
    service.sync_builtin_contracts(actor="principal:test")
    return repository, service


def test_platform_schema_and_manifest_cover_all_v2_subsystems(tmp_path: Path) -> None:
    repository, service = prepared(tmp_path)
    assert platform_schema()["properties"]["schema_version"]["const"] == PLATFORM_SCHEMA_VERSION
    manifest = service.manifest()
    assert manifest["schema_version"] == PLATFORM_SCHEMA_VERSION
    assert manifest["release_version"] == "2.0.0"
    assert manifest["migration_version"] == 13
    assert manifest["local_first"] is True
    assert manifest["platform_core_optional"] is True
    assert len(manifest["contracts"]) >= 12
    assert "platform-manifest" in manifest["capabilities"]
    assert manifest["counts"]["records"] == 0
    assert repository.health().healthy


def test_component_versions_links_and_events_are_governed(tmp_path: Path) -> None:
    repository, service = prepared(tmp_path)
    component = service.register_component(
        {
            "component_id": "component:decision-studio",
            "name": "Decision Studio",
            "product_code": "decision-studio",
            "component_type": "platform-product",
            "version": "2.0.0",
            "endpoint": "https://example.org/decision-studio",
            "capabilities": ["decision-evidence", "decision-packets"],
            "contracts": ["catalyst-data-handoff/1.0"],
            "metadata": {"optional": True},
        },
        actor="principal:test",
    )
    assert component["action"] == "inserted"
    assert service.components(status="active")[-1]["product_code"] in {"decision-studio", "catalyst-data"}
    versions = service.component_versions("component:decision-studio")
    assert versions[0]["version"] == "2.0.0"
    link = service.link(
        "component:catalyst-data",
        "component:decision-studio",
        "handoff",
        "decision-evidence",
        contract_id="catalyst-data-handoff/1.0",
        actor="principal:test",
    )
    assert link["status"] == "active"
    assert service.links(component_id="component:decision-studio")[0]["capability"] == "decision-evidence"
    assert any(item["event_type"] == "component_linked" for item in service.events())
    with sqlite3.connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE platform_component_versions SET version='9.9.9'")


def test_release_snapshot_is_checksum_bound_and_verifiable(tmp_path: Path) -> None:
    repository, service = prepared(tmp_path)
    ImportService(repository).run(ROOT / "examples/imports/records.json")
    first = service.create_snapshot(actor="principal:release")
    second = service.create_snapshot(actor="principal:release")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["manifest"]["counts"]["records"] == 2
    verification = service.verify_snapshot(first["snapshot_id"], actor="principal:reviewer")
    assert verification["status"] == "pass"
    with sqlite3.connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM platform_release_snapshots")


def test_integrated_platform_readiness_and_populated_rollback(tmp_path: Path) -> None:
    repository, service = prepared(tmp_path)
    result = service.readiness(actor="principal:test")
    assert result["schema_version"] == PLATFORM_SCHEMA_VERSION
    assert result["status"] in {"ready", "attention"}
    assert not any(item["status"] == "fail" for item in result["platform"]["checks"])
    assert repository.rollback(1) == [13]
    assert repository.health().migration_version == 12
    assert repository.migrate() == [13]
    assert repository.health().migration_version == 13
    assert service.components()[0]["component_id"] == "component:catalyst-data"


def test_platform_cli_workflow(tmp_path: Path, capsys) -> None:
    database = tmp_path / "cli.sqlite3"
    definition = tmp_path / "component.json"
    definition.write_text(json.dumps({
        "component_id": "component:workbench",
        "name": "Workbench",
        "product_code": "workbench",
        "component_type": "platform-product",
        "version": "5.0.0",
        "capabilities": ["calculation-input"],
        "contracts": ["catalyst-data-handoff/1.0"]
    }), encoding="utf-8")
    assert main(["init", str(database)]) == 0
    assert main(["platform-contract-sync", str(database)]) == 0
    assert main(["platform-register", str(database), str(definition)]) == 0
    assert main(["platform-link", str(database), "component:catalyst-data", "component:workbench", "handoff", "calculation-input"]) == 0
    assert main(["platform-snapshot", str(database)]) == 0
    assert main(["platform-readiness", str(database), "--no-persist"]) == 0
    output = capsys.readouterr().out
    assert "catalyst-data-platform/2.0" in output
    assert "component:workbench" in output


def _request_json(url: str, *, method: str = "GET", body=None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_v2_platform_http_discovery_registration_and_snapshot(tmp_path: Path) -> None:
    repository, service = prepared(tmp_path)
    key = ApiRegistry(repository).create_key("Platform integration", ["platform:read", "platform:write"])
    server = CatalystApiServer(("127.0.0.1", 0), repository)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, manifest = _request_json(base + "/v2/platform")
        assert status == 200
        assert manifest["schema_version"] == PLATFORM_SCHEMA_VERSION
        status, readiness = _request_json(base + "/v2/platform/readiness", token=key["token"])
        assert status == 200
        assert readiness["schema_version"] == PLATFORM_SCHEMA_VERSION
        status, registered = _request_json(
            base + "/v2/platform/components",
            method="POST",
            token=key["token"],
            body={
                "component_id": "component:knowledge-library",
                "name": "Knowledge Library",
                "product_code": "knowledge-library",
                "component_type": "platform-product",
                "version": "4.0.0",
                "capabilities": ["evidence-source"],
                "contracts": ["catalyst-data-handoff/1.0"],
            },
        )
        assert status == 200
        assert registered["component_id"] == "component:knowledge-library"
        status, snapshot = _request_json(base + "/v2/platform/snapshots", method="POST", token=key["token"], body={})
        assert status == 201
        assert service.verify_snapshot(snapshot["snapshot_id"], actor="principal:test")["status"] == "pass"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
