#!/usr/bin/env python3
"""Regenerate schema.sql from ordered migrations without repository data."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from catalyst_data.migrations import MigrationManager
from sync_contract import load_contract, generated_sql

EXCLUDED_VIEWS = {"measurement_review", "provenance_gaps", "low_confidence_measurements"}


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory) / "schema.sqlite3"
        connection = sqlite3.connect(db)
        connection.execute("PRAGMA foreign_keys=ON")
        MigrationManager(connection).migrate()
        rows = connection.execute(
            """SELECT rowid,type,name,sql FROM sqlite_master
               WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
               ORDER BY CASE type WHEN 'table' THEN 1 WHEN 'index' THEN 2 WHEN 'trigger' THEN 3 WHEN 'view' THEN 4 ELSE 5 END, rowid"""
        ).fetchall()
        connection.close()
    statements=[]
    for _, kind, name, sql in rows:
        if kind == "view" and name in EXCLUDED_VIEWS:
            continue
        statements.append(sql.rstrip(";") + ";")
    text = "-- Catalyst Data v1.8.0 current schema snapshot\n-- Repository initialization uses ordered migrations in python/catalyst_data/migrations.\nPRAGMA foreign_keys = ON;\nBEGIN TRANSACTION;\n" + "\n\n".join(statements) + "\nCOMMIT;\n\n" + generated_sql(load_contract()) + "\n"
    (ROOT / "schema.sql").write_text(text, encoding="utf-8")
    print("wrote schema.sql")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
