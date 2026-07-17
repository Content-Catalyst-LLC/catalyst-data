# Contributing

Catalyst Data welcomes practical improvements that preserve evidence discipline, contract stability, and explicit uncertainty.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
python3 scripts/build_release.py
python3 scripts/check_release.py
```

## Canonical sources

Edit these source files when changing contracts:

- `VERSION`
- `contracts/review_contract.json`
- `contracts/record_contract.json`
- `scripts/sync_contract.py`
- `scripts/sync_record_contract.py`

Do not hand-edit generated files:

- `python/catalyst_data/_version.py`
- `python/catalyst_data/_contract.py`
- `python/catalyst_data/_record_contract.py`
- `python/catalyst_data/schemas/catalyst_data_record_1_0.schema.json`
- `schemas/catalyst_data_record_1_0.schema.json`
- `schemas/catalyst_data_export.schema.json`
- `wordpress/catalyst-data-demo/assets/catalyst-data-contract.js`
- `wordpress/catalyst-data-demo/assets/catalyst-data-record-contract.js`
- the generated review-view region of `schema.sql`
- `dist/catalyst-data-demo.zip`

Run `python3 scripts/build_release.py` after changing a canonical source.

## Standards

- Keep examples educational and clearly labeled.
- Do not imply compliance certification or verified impact.
- Preserve source, method, assumptions, limitations, uncertainty, and review context.
- Keep evidence readiness separate from measurement direction.
- Reject unknown core properties; use namespaced extensions.
- Recalculate legacy derived fields rather than trusting them.
- Add or update schema, semantic, parity, migration, and packaging tests with every contract change.
