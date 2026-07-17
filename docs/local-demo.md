# Local Demo

## Persistent SQLite repository

```bash
catalyst-data init catalyst-data.sqlite3
catalyst-data import catalyst-data.sqlite3 examples/imports/records.json
catalyst-data status catalyst-data.sqlite3
catalyst-data review catalyst-data.sqlite3
catalyst-data export catalyst-data.sqlite3 outputs/repository-export.json
```

The supported repository workflow uses ordered migrations. `schema.sql` remains a current-schema reference and SQL review demo:

```bash
sqlite3 catalyst_data-demo.db < schema.sql
sqlite3 catalyst_data-demo.db < queries.sql
sqlite3 catalyst_data-demo.db "SELECT * FROM measurement_review;"
```

## Record utilities

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

Install `dist/catalyst-data-demo.zip`, activate the plugin, and add `[catalyst_data_demo]` to a page. The shortcode is a browser-only contract demonstration and does not persist records.
