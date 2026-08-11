from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.adapters import AdapterRunner, AdapterValidationError, default_adapter_registry
from catalyst_data.connectors import ConnectorService
from catalyst_data.database import connect
from catalyst_data.repository import CatalystRepository


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def read(self, limit=-1):
        return self.body if limit is None or limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def http_connector() -> dict:
    definition = json.loads((ROOT / "examples/connectors/open_metrics_connector.json").read_text(encoding="utf-8"))
    definition["connector_id"] = "connector:adapter-metrics"
    definition["name"] = "Adapter Metrics"
    definition["connector_type"] = "http-json"
    definition["source"]["uri"] = "https://api.example.test/metrics"
    definition["schedule"] = {"enabled": False, "frequency_minutes": 60}
    return definition


def metric(record_id: str, current: float) -> dict:
    return {
        "id": record_id,
        "entity_name": "Adapter Test Program",
        "entity_type": "program",
        "indicator_name": "Coverage score",
        "unit": "score",
        "direction": "higher",
        "framework": "Adapter Test",
        "indicator_version": "1.0",
        "period_label": record_id[-7:],
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "baseline": 50,
        "current": current,
        "confidence": 80,
        "confidence_basis": "Adapter fixture",
        "method_notes": "Adapter fixture",
        "updated_at": "2026-08-11T05:00:00Z",
    }


def test_builtin_adapter_registry_exposes_governed_manifests():
    manifests = default_adapter_registry().list()
    assert [item["adapter_id"] for item in manifests] == ["generic-http-csv", "generic-http-json", "internet-archive-metadata", "internet-archive-search", "un-sdg-geoareas", "un-sdg-goals", "un-sdg-indicator-data", "un-sdg-indicators", "wayback-availability", "wayback-cdx", "world-bank-countries", "world-bank-indicator-data", "world-bank-indicators"]
    assert all(item["schema_version"] == "catalyst-data-source-adapter/1.0" for item in manifests)
    assert "conditional-get" in manifests[1]["capabilities"]
    assert set(manifests[1]["pagination"]) == {"none", "page", "offset", "cursor"}


def test_binding_requires_connector_response_format(tmp_path):
    repository = CatalystRepository(tmp_path / "adapter.db")
    connector = http_connector()
    ConnectorService(repository).register(connector)
    runner = AdapterRunner(repository)
    with pytest.raises(AdapterValidationError, match="requires connector_type http-csv"):
        runner.bind(connector["connector_id"], "generic-http-csv", {"base_url": connector["source"]["uri"]})


def test_paginated_adapter_fetches_pages_then_uses_governed_connector_engine(tmp_path):
    repository = CatalystRepository(tmp_path / "adapter-run.db")
    connector = http_connector()
    ConnectorService(repository).register(connector)

    requested = []
    def opener(request, timeout=30):
        requested.append(request.full_url)
        page = int(parse_qs(urlparse(request.full_url).query).get("page", ["1"])[0])
        if page == 1:
            return FakeResponse({"records": [metric("metric-2026-Q1", 62)]}, headers={"Content-Type":"application/json", "ETag":"\"page-one\""})
        if page == 2:
            return FakeResponse({"records": [metric("metric-2026-Q2", 68)]}, headers={"Content-Type":"application/json"})
        return FakeResponse({"records": []}, headers={"Content-Type":"application/json"})

    runner = AdapterRunner(repository, opener=opener)
    binding = runner.bind(connector["connector_id"], "generic-http-json", {
        "base_url": connector["source"]["uri"],
        "records_path": "records",
        "pagination": {"type": "page", "param": "page", "start": 1, "max_pages": 5},
    })
    assert binding["adapter_id"] == "generic-http-json"
    result = runner.run(connector["connector_id"])
    assert result["adapter_run"]["status"] == "succeeded"
    assert result["adapter_run"]["page_count"] == 3
    assert result["adapter_run"]["row_count"] == 2
    assert result["connector_run"]["run"]["inserted_count"] == 2
    assert len(requested) == 3

    records = repository.list_records(limit=10)
    assert len(records) == 2
    extension = records[0]["extensions"]["org.sustainablecatalyst.source-adapter"]
    assert extension["adapter_id"] == "generic-http-json"
    assert extension["adapter_version"] == "1.0.0"
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM connector_adapter_pages").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM connector_runs").fetchone()[0] == 1


def test_conditional_get_304_skips_connector_ingestion(tmp_path):
    repository = CatalystRepository(tmp_path / "conditional.db")
    connector = http_connector()
    ConnectorService(repository).register(connector)
    calls = {"count": 0}

    def opener(request, timeout=30):
        calls["count"] += 1
        if calls["count"] == 1:
            return FakeResponse({"records": [metric("metric-2026-Q1", 62)]}, headers={"Content-Type":"application/json", "ETag":"\"v1\""})
        assert request.headers.get("If-none-match") == '"v1"'
        raise HTTPError(request.full_url, 304, "Not Modified", {"ETag": '"v1"'}, io.BytesIO(b""))

    runner = AdapterRunner(repository, opener=opener)
    runner.bind(connector["connector_id"], "generic-http-json", {"base_url": connector["source"]["uri"], "records_path": "records"})
    first = runner.run(connector["connector_id"])
    second = runner.run(connector["connector_id"])
    assert first["connector_run"]["run"]["inserted_count"] == 1
    assert second["adapter_run"]["checkpoint"]["not_modified"] is True
    assert second["connector_run"] is None
    assert len(ConnectorService(repository).runs()) == 1


def test_migration_fifteen_rolls_back_adapter_tables(tmp_path):
    repository = CatalystRepository(tmp_path / "migration15.db")
    repository.initialize(target=15)
    assert repository.health().migration_version == 15
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='connector_adapter_bindings'").fetchone()
    assert repository.rollback(1) == [15]
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='connector_adapter_bindings'").fetchone() is None
    assert repository.migrate(target=15) == [15]


def test_adapter_config_rejects_persisted_credentials():
    adapter = default_adapter_registry().get("generic-http-json")
    with pytest.raises(AdapterValidationError, match="must not persist credentials"):
        adapter.normalize_config({"base_url": "https://example.org/data", "headers": {"Authorization": "Bearer secret"}})
    with pytest.raises(AdapterValidationError, match="must not persist credentials"):
        adapter.normalize_config({"base_url": "https://example.org/data", "query": {"api_key": "secret"}})
