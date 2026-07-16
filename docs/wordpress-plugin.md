# WordPress Plugin

The WordPress demo plugin provides `[catalyst_data_demo]`. It is browser-based and generates structured JSON without sending user inputs to a server.

## Distribution

The committed source is in `wordpress/catalyst-data-demo/`. The installable ZIP is generated deterministically at `dist/catalyst-data-demo.zip` by:

```bash
python3 scripts/build_release.py
```

Do not edit files inside the ZIP directly.

## v1.0.1 repairs

- Loads the generated browser review contract before the demo engine.
- Uses the same thresholds and status labels as Python and SQLite.
- Treats zero-baseline change as indeterminate.
- Separates review status from signal status.
- Generates unique field IDs when the shortcode appears more than once on a page.
