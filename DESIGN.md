# Catalyst Data Design Document

Catalyst Data is the canonical evidence and measurement record layer for Sustainable Catalyst.

It exists to answer these practical questions:

1. Which entity and indicator are being measured?
2. Which reporting period and measurement values apply?
3. Which source supports the record, under what license and access conditions?
4. Which method, assumptions, limitations, and uncertainty produced the value?
5. How confident is the record, and why?
6. What evidence-readiness and directional judgments have been derived?
7. Which versioned contract and stable identifiers allow the record to move safely between products?

## Contract architecture

- `contracts/review_contract.json` governs confidence thresholds and directional classification.
- `contracts/record_contract.json` governs record types, enums, ID patterns, provenance vocabulary, quality flags, and extension rules.
- `schemas/catalyst_data_record_1_0.schema.json` is the normative exchange schema.
- Python and browser artifacts are generated from those contracts.
- Cross-field semantic validation verifies derived percentage change and review judgments.

## Extension boundary

The core schema rejects unknown fields. Product-specific metadata belongs under namespaced `extensions` keys so integrations can add context without mutating the canonical meaning of core fields.

## Scope

Catalyst Data supports structured measurement, provenance discipline, strict validation, legacy conversion, and reviewable exports. It is designed to interoperate with Knowledge Library, Research Librarian, Site Intelligence, Workbench, Research Lab, Catalyst Analytics R, Catalyst Canvas, Decision Studio, and Platform Core through later typed handoffs.

## Boundary

Catalyst Data validates record structure and derived contract logic. It does not verify source truth, certify compliance, or guarantee impact.
