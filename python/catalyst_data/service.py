from __future__ import annotations

from pathlib import Path

from .exporter import export_repository
from .importer import ImportService, ImportSummary
from .repository import CatalystRepository


class CatalystDataService:
    """Application service joining repository, migration, import, review, and export operations."""

    def __init__(self, database: str | Path):
        self.repository = CatalystRepository(database)
        self.imports = ImportService(self.repository)

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
