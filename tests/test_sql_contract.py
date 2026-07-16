from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import classify_review, classify_signal


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript((ROOT / "schema.sql").read_text())
    connection.executescript((ROOT / "queries.sql").read_text())
    return connection


def test_seeded_views_match_python_contract():
    connection = database()
    rows = connection.execute(
        "SELECT confidence, source, direction, percent_change, review_status, signal_status FROM measurement_review"
    ).fetchall()
    assert len(rows) == 2
    for confidence, source, direction, change, review, signal in rows:
        assert review == classify_review(confidence, source)
        assert signal == classify_signal(change, direction)


def test_zero_baseline_is_indeterminate_in_sql():
    connection = database()
    connection.execute(
        """
        INSERT INTO measurements(entity_id, indicator_id, period_id, source_id, value, baseline_value, confidence, method)
        SELECT e.id, i.id, p.id, s.id, 50, 0, 90, 'Zero baseline test'
        FROM entities e, indicators i, periods p, sources s
        WHERE e.name='Catalyst Demo Organization'
          AND i.name='Participation rate'
          AND p.label='2026-Q1'
          AND s.name='Public energy benchmark dataset'
        """
    )
    percent, signal = connection.execute(
        "SELECT percent_change, signal_status FROM measurement_review WHERE method='Zero baseline test'"
    ).fetchone()
    assert percent is None
    assert signal == "indeterminate"
