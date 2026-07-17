# Analysis Artifacts and Reproducible Data Packages

Catalyst Data v1.11.0 records the exact data, parameters, environment, code reference, outputs, provenance, and review state used by an analysis. The analysis layer does not execute arbitrary third-party code. It governs the inputs and outputs of analytical work performed in Catalyst Data, Workbench, Research Lab, Catalyst Analytics R, Decision Studio, or another declared system.

## Contract

Analysis definitions use `catalyst-data-analysis-artifact/1.0`. A definition identifies the workspace, immutable version, analysis type, input records and roles, parameters, runtime environment, code revision, expected outputs, and platform links.

## Immutable history

- Analysis versions and activations are append-only.
- Every run freezes canonical input payloads and SHA-256 checksums.
- Outputs are stored with media type, checksum, byte size, and metadata.
- Derived measurements retain links to each source record and the producing run.
- Replication reviews are append-only.
- Package exports retain their manifest and package checksum.

## Upstream invalidation

When a canonical input record changes, migration 011 automatically creates an invalidation event for every affected run. The original frozen input is preserved. The event warns that the analytical result may need to be rerun; it does not erase or silently rewrite the historical result.

## Reproducible packages

`analysis-package` creates a deterministic ZIP or directory containing:

- Analysis definition
- Parameters
- Runtime environment and code reference
- Frozen canonical input records
- Output files and output index
- Record provenance
- Review and approval history
- Invalidation warnings
- Replication reviews
- Manifest and SHA-256 checksums

Rebuilding a package for the same unchanged run produces byte-identical ZIP output.

## CLI workflow

```bash
catalyst-data analysis-register catalyst-data.sqlite3 examples/analyses/evidence_quality_analysis.json
catalyst-data analysis-run catalyst-data.sqlite3 analysis:evidence-quality-summary
catalyst-data analysis-runs catalyst-data.sqlite3 --artifact-id analysis:evidence-quality-summary
catalyst-data analysis-package catalyst-data.sqlite3 ANALYSIS_RUN_ID outputs/evidence-quality-package.zip
```

Inspect changes and replication:

```bash
catalyst-data analysis-invalidate catalyst-data.sqlite3 --run-id ANALYSIS_RUN_ID
catalyst-data analysis-replication-review catalyst-data.sqlite3 ANALYSIS_RUN_ID confirmed reviewer@example.org --notes "Independent rerun matched."
catalyst-data analysis-run-show catalyst-data.sqlite3 ANALYSIS_RUN_ID
```

## Boundaries

Catalyst Data records reproducibility evidence and invalidation warnings. It does not certify scientific validity, replace peer review, or allow AI systems to approve analyses. Human review, interpretation, and publication decisions remain explicit.
