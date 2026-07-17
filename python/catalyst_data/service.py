from __future__ import annotations

from pathlib import Path

from .exporter import export_repository
from .importer import ImportService, ImportSummary
from .repository import CatalystRepository
from .public_api import ApiRegistry
from .handoff import create_handoff


class CatalystDataService:
    """Application service joining repository, migration, import, review, and export operations."""

    def __init__(self, database: str | Path):
        self.repository = CatalystRepository(database)
        self.imports = ImportService(self.repository)
        self.api = ApiRegistry(self.repository)

    def initialize(self) -> list[int]:
        return self.repository.initialize()

    def import_file(self, source: str | Path, **options) -> ImportSummary:
        return self.imports.run(source, **options)

    def export_file(self, destination: str | Path, *, format_name: str = "json") -> int:
        return export_repository(self.repository, destination, format_name=format_name)

    def evidence(self, record_id: str):
        return self.repository.evidence(record_id)

    def provenance(self, record_id: str, *, limit: int = 200):
        return self.repository.provenance(record_id, limit=limit)

    def source_history(self, source_id: str | None = None, *, limit: int = 100):
        return self.repository.source_history(source_id, limit=limit)

    def indicators(self, indicator_id: str | None = None, *, limit: int = 100):
        return self.repository.indicator_registry(indicator_id, limit=limit)

    def methodologies(self, methodology_id: str | None = None, *, limit: int = 100):
        return self.repository.methodology_history(methodology_id, limit=limit)

    def units(self, unit_id: str | None = None, *, limit: int = 100):
        return self.repository.unit_registry(unit_id, limit=limit)

    def compare(self, left_record_id: str, right_record_id: str):
        return self.repository.compare(left_record_id, right_record_id)

    def convert(self, value: float, from_unit_id: str, to_unit_id: str):
        return self.repository.convert(value, from_unit_id, to_unit_id)

    def questions(self, question_id: str | None = None, *, limit: int = 100):
        return self.repository.questions(question_id, limit=limit)

    def instruments(self, instrument_id: str | None = None, *, limit: int = 100):
        return self.repository.instruments(instrument_id, limit=limit)

    def datasets(self, dataset_id: str | None = None, *, limit: int = 100):
        return self.repository.datasets(dataset_id, limit=limit)

    def observations(self, record_id: str | None = None, *, quality_status: str | None = None, limit: int = 200):
        return self.repository.observations(record_id, quality_status=quality_status, limit=limit)

    def lineage(self, record_id: str):
        return self.repository.lineage(record_id)

    def create_api_key(self, name: str, scopes):
        return self.api.create_key(name, scopes)

    def create_handoff(self, record_ids, *, target_product: str, target_capability: str, source_version: str, api_base_url: str | None = None):
        records=[]
        for record_id in record_ids:
            record=self.repository.get_record(record_id)
            if record is None:
                raise KeyError(record_id)
            records.append(record)
        return create_handoff(records, target_product=target_product, target_capability=target_capability, source_version=source_version, api_base_url=api_base_url)
