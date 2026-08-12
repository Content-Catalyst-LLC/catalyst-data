from __future__ import annotations

import json
import threading
from urllib.request import urlopen

import pytest

from catalyst_data.database import connect
from catalyst_data.dataset_catalog import DatasetCatalogService
from catalyst_data.public_api import CatalystApiServer
from catalyst_data.repository import CatalystRepository

NOW = "2026-08-11T23:00:00Z"


def _seed(repository: CatalystRepository) -> None:
    with connect(repository.path) as connection:
        connection.execute(
            """INSERT INTO world_bank_indicators(indicator_code,name,unit,source_note,source_organization,topics_json,metadata_json,source_uri,fetched_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("SP.POP.TOTL", "Population, total", "people", "Total population.", "World Bank", "[]", "{}", "https://api.worldbank.org/v2/indicator/SP.POP.TOTL", NOW, NOW),
        )
        connection.execute(
            """INSERT INTO world_bank_observations(observation_id,country_code,country_name,indicator_code,indicator_name,period,value_numeric,unit,source_id,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("wb:1", "KEN", "Kenya", "SP.POP.TOTL", "Population, total", "2025", 55000000, "people", "2", "{}", "https://api.worldbank.org/v2/country/KEN/indicator/SP.POP.TOTL", NOW, NOW, NOW),
        )
        connection.execute(
            """INSERT INTO erddap_datasets(dataset_key,server_url,dataset_id,title,institution,service_kind,metadata_json,source_uri,first_seen_at,fetched_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ("erddap:test:ocean", "https://example.test/erddap", "ocean_test", "Ocean Temperature Test", "NOAA", "tabledap", "{}", "https://example.test/erddap/info/ocean_test/index.json", NOW, NOW, NOW),
        )
        connection.execute(
            """INSERT INTO earth_climate_observations(observation_id,provider,dataset_id,source_native_id,metric_code,period,value_numeric,unit,latitude,longitude,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("eco:1", "erddap", "ocean_test", "row:1", "temperature", "2026-08-11T22:00:00Z", 18.2, "degree_C", 41.8, -87.6, "{}", "https://example.test/erddap/tabledap/ocean_test.json", NOW, NOW, NOW),
        )
        connection.commit()


def test_dataset_catalog_sync_search_and_idempotence(tmp_path):
    repository = CatalystRepository(tmp_path / "catalog.sqlite3")
    repository.initialize()
    _seed(repository)
    service = DatasetCatalogService(repository)

    first = service.sync()
    assert first["entries"] >= 6
    population = service.search(query="Population", provider="world-bank")
    assert len(population) == 1
    assert population[0]["dataset_key"] == "SP.POP.TOTL"
    assert population[0]["record_count"] == 1
    assert population[0]["metadata"]["indicator_code"] == "SP.POP.TOTL"
    ocean = service.search(query="Ocean Temperature", provider="erddap")
    assert ocean[0]["resource_kind"] == "earth-ocean-dataset"
    assert ocean[0]["record_count"] == 1

    second = service.sync()
    assert second["entries"] == first["entries"]
    assert len(service.search(provider="world-bank")) == 1
    status = service.status()
    assert status["active_dataset_count"] == first["entries"]
    assert status["provider_count"] >= 5
    assert status["indexed_record_count"] >= 2


def test_dataset_catalog_sync_history_is_immutable(tmp_path):
    repository = CatalystRepository(tmp_path / "immutable.sqlite3")
    repository.initialize()
    DatasetCatalogService(repository).sync()
    with connect(repository.path) as connection:
        with pytest.raises(Exception, match="immutable"):
            connection.execute("DELETE FROM dataset_catalog_sync_runs")


def test_migration_twenty_one_rollback_and_reapply(tmp_path):
    repository = CatalystRepository(tmp_path / "migration21.sqlite3")
    repository.initialize(target=21)
    assert repository.health().migration_version == 21
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='dataset_catalog_status'").fetchone()
    assert repository.rollback(1) == [21]
    assert repository.health().migration_version == 20
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='dataset_catalog_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='space_science_status'").fetchone() is not None
    assert repository.migrate(target=21) == [21]


def test_public_dataset_catalog_api_reads_index_only(tmp_path):
    repository = CatalystRepository(tmp_path / "public-catalog.sqlite3")
    repository.initialize()
    _seed(repository)
    service = DatasetCatalogService(repository)
    service.sync()
    server = CatalystApiServer(("127.0.0.1", 0), repository, allow_origin="https://sustainablecatalyst.com")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/v1/catalog/datasets?query=Population&provider=world-bank", timeout=5) as response:
            body = json.loads(response.read())
        assert body["datasets"][0]["dataset_key"] == "SP.POP.TOTL"
        catalog_id = body["datasets"][0]["catalog_id"]
        with urlopen(base + "/v1/catalog/datasets/" + catalog_id, timeout=5) as response:
            item = json.loads(response.read())
        assert item["provider"] == "world-bank"
        with urlopen(base + "/v1/catalog/status", timeout=5) as response:
            status = json.loads(response.read())
        assert status["active_dataset_count"] >= 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
