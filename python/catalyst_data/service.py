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
