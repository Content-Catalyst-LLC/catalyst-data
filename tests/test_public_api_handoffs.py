from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from catalyst_data import CatalystRepository, ImportService
from catalyst_data.handoff import HandoffValidationError, create_handoff, validate_handoff
from catalyst_data.public_api import ApiRegistry, CatalystApiServer, openapi_document, public_projection
from catalyst_data.workspaces import WorkspaceService

ROOT = Path(__file__).resolve().parents[1]


def populated_repository(tmp_path: Path) -> CatalystRepository:
    repository = CatalystRepository(tmp_path / "api.sqlite3")
    repository.initialize()
    ImportService(repository).run(ROOT / "examples/imports/records.json")
    return repository


def approve(repository: CatalystRepository, record_id: str) -> None:
    repository.assign_review(record_id, "reviewer@example.org", "author@example.org")
    repository.submit_review(record_id, "author@example.org", "Ready")
    repository.start_review(record_id, "reviewer@example.org")
    repository.decide_review(record_id, "approved", "reviewer@example.org", reason="Approved for public API")
    WorkspaceService(repository).set_visibility(record_id, "public", "public", actor="publisher@example.org")


def request_json(url: str, *, method: str = "GET", body=None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_migration_008_and_api_registry_are_persistent(tmp_path):
    repository = populated_repository(tmp_path)
    assert repository.health().migration_version == 11
    registry = ApiRegistry(repository)
    created = registry.create_key("Decision Studio", ["records:write", "handoffs:write"])
    assert created["token"].startswith("cd_")
    listed = registry.list_keys()
    assert listed[0]["key_id"] == created["key_id"]
    assert "token" not in listed[0]
    assert registry.authenticate(created["token"], "records:write") is not None
    assert registry.revoke(created["key_id"])
    assert registry.authenticate(created["token"], "records:write") is None


def test_public_projection_requires_external_approval_and_redacts_internal_fields(tmp_path):
    repository = populated_repository(tmp_path)
    record = repository.list_records(limit=1)[0]
    with pytest.raises(PermissionError):
        public_projection(record)
    approve(repository, record["record_id"])
    repository.add_review_comment(record["record_id"], "reviewer@example.org", "Internal", visibility="internal")
    repository.add_review_comment(record["record_id"], "reviewer@example.org", "Public note", visibility="public")
    projected = public_projection(repository.get_record(record["record_id"]))
    assert projected["review_workflow"]["assigned_reviewers"] == []
    assert projected["review_workflow"]["decisions"] == []
    assert [item["body"] for item in projected["review_workflow"]["comments"]] == ["Public note"]
    assert projected["source"]["access_notes"] is None
    assert all(item["raw_payload"] == {} for item in projected["observation_lineage"]["observations"])


def test_typed_handoff_is_valid_and_receipt_is_immutable(tmp_path):
    repository = populated_repository(tmp_path)
    record = repository.list_records(limit=1)[0]
    handoff = create_handoff([record], target_product="decision-studio", target_capability="decision-evidence", source_version="1.11.0", api_base_url="https://data.example.org")
    assert validate_handoff(handoff)["schema_version"] == "catalyst-data-handoff/1.0"
    assert handoff["records"][0]["href"].startswith("https://data.example.org/v1/records/")
    receipt = ApiRegistry(repository).receive_handoff(handoff)
    assert receipt["status"] == "accepted"
    assert ApiRegistry(repository).receipts()[0]["handoff_id"] == handoff["handoff_id"]
    connection = sqlite3.connect(repository.path)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM handoff_receipts").fetchall()
    connection.close()


def test_handoff_rejects_unsupported_products(tmp_path):
    repository = populated_repository(tmp_path)
    record = repository.list_records(limit=1)[0]
    with pytest.raises(HandoffValidationError):
        create_handoff([record], target_product="unknown-product", target_capability="records", source_version="1.11.0")


def test_http_api_public_reads_protected_writes_openapi_and_handoffs(tmp_path):
    repository = populated_repository(tmp_path)
    records = repository.list_records(limit=2)
    approve(repository, records[0]["record_id"])
    key = ApiRegistry(repository).create_key("Integration test", ["records:write", "handoffs:write"])
    server = CatalystApiServer(("127.0.0.1", 0), repository, allow_origin="https://sustainablecatalyst.com")
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, health = request_json(base + "/health")
        assert status == 200 and health["migration_version"] == 11
        status, page = request_json(base + "/v1/records")
        assert status == 200 and page["pagination"]["total"] == 1
        assert page["records"][0]["record_id"] == records[0]["record_id"]
        try:
            request_json(base + "/v1/records", method="POST", body=records[1])
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("protected write accepted without token")
        status, stored = request_json(base + "/v1/records", method="POST", body=records[1], token=key["token"])
        assert status == 200 and stored["record_id"] == records[1]["record_id"]
        handoff = create_handoff([records[0]], target_product="workbench", target_capability="calculation-input", source_version="1.11.0")
        status, accepted = request_json(base + "/v1/handoffs", method="POST", body=handoff, token=key["token"])
        assert status == 202 and accepted["handoff_id"] == handoff["handoff_id"]
        status, spec = request_json(base + "/v1/openapi.json")
        assert status == 200 and spec["openapi"] == "3.1.0"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert repository.stats()["api_audit_events"] >= 3


def test_openapi_declares_public_and_protected_surfaces():
    spec = openapi_document("https://data.sustainablecatalyst.com")
    assert spec["openapi"] == "3.1.0"
    assert "/v1/records" in spec["paths"]
    assert spec["paths"]["/v1/records"]["post"]["security"] == [{"bearerAuth": []}]
    assert "/v1/connectors" in spec["paths"]
    assert "/v1/connectors/{connector_id}/run" in spec["paths"]
