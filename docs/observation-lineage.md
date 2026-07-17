# Questions, Instruments, Datasets, and Observations

Catalyst Data v1.5.0 introduces `catalyst-data-observation-lineage/1.0`, a backward-compatible section of the canonical measurement record that makes the path from a research or decision question to a published measurement explicit.

## Lineage path

The contract models:

1. **Question** — the research, monitoring, evaluation, or decision question that gives the measurement purpose.
2. **Instrument** — the survey, sensor, form, API, administrative system, model, or manual protocol used to collect data.
3. **Dataset** — a versioned collection with field definitions, licensing, access classification, and optional checksum.
4. **Observation batch** — a bounded collection run linking one dataset version to one instrument version.
5. **Observation** — a governed raw or intermediate value with time, unit, quality state, dimensions, and missing/outlier/imputation metadata.
6. **Transformation** — an explicit operation linking one or more observations to the canonical measurement fields.

## Persistent tables

Migration 005 adds:

- `research_questions`
- `instruments` and immutable `instrument_versions`
- `instrument_fields`
- `datasets` and immutable `dataset_versions`
- `dataset_fields`
- `observation_batches`
- `observations`
- `observation_dimensions`
- `measurement_questions`
- `measurement_observations`
- `observation_transformations`
- `transformation_inputs`
- append-only `lineage_events`

Current registry and measurement summaries are available through `instrument_registry_current`, `dataset_registry_current`, and `observation_lineage_summary`.

## Backward compatibility

The canonical record remains `catalyst-data-record/1.0`. Records created before v1.5.0 may omit `observation_lineage`; the builder and repository normalize those records when they are imported or migrated. Migration 005 does not delete or replace existing canonical records.

## Quality semantics

Observation quality states are `valid`, `missing`, `censored`, `outlier`, `imputed`, and `rejected`. Missing observations require a reason. Outlier and imputation details remain visible rather than being hidden inside a final measurement.

## CLI inspection

```bash
catalyst-data questions catalyst-data.sqlite3
catalyst-data instruments catalyst-data.sqlite3
catalyst-data datasets catalyst-data.sqlite3
catalyst-data observations catalyst-data.sqlite3 --record-id RECORD_ID
catalyst-data lineage catalyst-data.sqlite3 RECORD_ID
```

## Boundary

Catalyst Data records how observations and transformations produced a measurement. It does not claim that an instrument is scientifically valid, that a dataset is representative, or that a transformation is appropriate without human review.
