# Review, Quality, and Revision Workflow

Catalyst Data v1.6.0 adds a human-governed workflow around canonical records without replacing the existing evidence-readiness classification. Evidence readiness continues to describe whether a record is sufficiently sourced and confident; the review workflow describes who reviewed it, what decision was made, whether it may be published, and which immutable record version was approved.

## Contract

Current records include an optional, backward-compatible `review_workflow` object using `catalyst-data-review-workflow/1.0`. New and upgraded records are normalized with this object automatically.

The workflow contains:

- lifecycle state and priority;
- assigned reviewer identities;
- six quality dimensions and an explainable overall score;
- publication-gate status and reasons;
- semantic revision metadata;
- append-only decisions and comments.

## Workflow states

The supported lifecycle is:

`draft → submitted → in-review → approved`

A reviewer may instead request changes or reject a record. Approved records may later be superseded or archived. Invalid transitions are rejected by the application layer.

## Quality assessment

Quality is assessed independently across completeness, validity, consistency, timeliness, provenance, and uncertainty. Each dimension is scored from 0 to 100 and may include a written basis. The overall score is deterministic and does not replace reviewer judgment.

## Publication gates

- `blocked` means the record cannot be published.
- `internal` means it may be used inside a governed workspace but is not approved for external claims.
- `external` means an approval decision and the record’s quality/evidence state permit publication.

An external gate stores the approving actor and approval timestamp. The database also stores an immutable snapshot of the exact canonical payload approved by that decision.

## Revision history

Every repository write already creates an immutable canonical revision. v1.6.0 adds semantic revision diffs that record the action, summary, reason, actor, previous payload checksum, and changed paths. Review comments, decisions, quality assessments, and approval snapshots are append-only.

## CLI examples

```bash
catalyst-data reviews catalyst-data.sqlite3
catalyst-data review-assign catalyst-data.sqlite3 RECORD_ID reviewer@example.org --actor author@example.org
catalyst-data review-submit catalyst-data.sqlite3 RECORD_ID --actor author@example.org --notes "Ready for review"
catalyst-data review-start catalyst-data.sqlite3 RECORD_ID --actor reviewer@example.org
catalyst-data quality-assess catalyst-data.sqlite3 RECORD_ID quality-assessment.json --actor reviewer@example.org
catalyst-data review-comment catalyst-data.sqlite3 RECORD_ID --actor reviewer@example.org --body "Method is reproducible."
catalyst-data review-decide catalyst-data.sqlite3 RECORD_ID approved --actor reviewer@example.org --reason "Evidence and method are sufficient"
catalyst-data review-history catalyst-data.sqlite3 RECORD_ID
catalyst-data revisions catalyst-data.sqlite3 RECORD_ID
```

## Governance boundary

Catalyst Data records review history and publication decisions. It does not certify that a measurement is true, legally compliant, or suitable for every downstream use. Human reviewers and institutional policies remain responsible for approval decisions.
