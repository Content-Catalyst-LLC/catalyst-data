# Local Demo

## SQLite

```bash
sqlite3 catalyst_data.db < schema.sql
sqlite3 catalyst_data.db < queries.sql
sqlite3 catalyst_data.db "SELECT * FROM measurement_review;"
```

## Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .

catalyst-data brief examples/sample_project.json outputs/generated_brief.md
catalyst-data validate outputs/generated_brief.json
catalyst-data upgrade examples/sample_legacy_v1_0_record.json outputs/upgraded_legacy_record.json
```

## WordPress

Install `dist/catalyst-data-demo.zip`, activate the plugin, and add `[catalyst_data_demo]` to a page.
