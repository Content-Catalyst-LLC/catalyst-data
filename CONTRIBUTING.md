# Contributing

Catalyst Data welcomes practical improvements that preserve the module's evidence discipline.

Good contributions improve traceability, schema clarity, reproducibility, documentation, validation, or interoperability with Sustainable Catalyst modules.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
python3 scripts/build_release.py
python3 scripts/check_release.py
```

## Generated files

Edit `VERSION` and `contracts/review_contract.json`, then run the build script. Do not hand-edit:

- `python/catalyst_data/_version.py`
- `python/catalyst_data/_contract.py`
- `wordpress/catalyst-data-demo/assets/catalyst-data-contract.js`
- the generated review-view region of `schema.sql`
- `dist/catalyst-data-demo.zip`

## Standards

- Keep examples educational and clearly labeled.
- Do not imply compliance certification or verified impact.
- Preserve provenance: entity, indicator, period, measurement, source, confidence, and review notes.
- Keep evidence readiness separate from measurement direction.
- Add or update parity tests when changing review behavior.
