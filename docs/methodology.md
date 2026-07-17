# Catalyst Data Methodology

Catalyst Data follows a simple evidence standard:

```text
entity → indicator → period → measurement → source → confidence → review
```

The goal is not to make data look more certain than it is. The goal is to make measurement work traceable, reviewable, and reusable.

## Review status

Evidence readiness is classified using the canonical contract in `contracts/review_contract.json`:

- missing source → `missing source`
- confidence below 40 → `needs evidence`
- confidence from 40 through 69.999… → `reviewable with caution`
- confidence of 70 or higher → `reviewable`

Missing source takes precedence over confidence.

## Signal status

Measurement direction is evaluated separately:

- missing or zero baseline → `indeterminate`
- no change → `unchanged`
- neutral indicator → `descriptive`
- movement in the preferred direction → `improving`
- movement against the preferred direction → `declining`

Signal direction never upgrades evidence readiness.
