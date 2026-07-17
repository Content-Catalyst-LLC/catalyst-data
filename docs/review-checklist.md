# Review Checklist

Before treating a Catalyst Data record as reviewable, confirm:

- `$schema` and `schema_version` identify `catalyst-data-record/1.0`.
- Record, entity, indicator, period, and source IDs are present and stable.
- Creation, update, retrieval, and period dates are internally consistent.
- The entity, indicator, unit, direction, and reporting period are explicit.
- Baseline and current values use compatible units.
- Percentage change matches the supplied values or is `null` for a missing or zero baseline.
- A named source includes available publisher, licensing, citation, access, and integrity details.
- Confidence includes both a score and its basis.
- Method assumptions, limitations, uncertainty, and quality flags are visible.
- `review.status` reflects evidence readiness rather than whether the value improved.
- `review.signal_status` reflects direction without implying evidence quality.
- Product-specific fields are stored only under namespaced `extensions` keys.
- Reviewer notes explain any remaining caveats before publication or handoff.
