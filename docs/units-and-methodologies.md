# Units and Methodologies

## Governed units

A unit definition contains a stable ID, symbol, name, dimension, canonical unit ID, conversion factor, and conversion offset.

Catalyst Data uses:

`canonical_value = value × conversion_factor + conversion_offset`

A target value is recovered from the canonical value using the target unit's factor and offset. Conversion is rejected when dimensions or canonical unit bases differ.

## Methodology versions

Methodologies include a stable ID, version, title, description, optional formula, references, lifecycle status, approval metadata, and revision notes.

Approved methodologies require both `approved_by` and `approved_at`. Methodology versions are immutable in the persistent repository.

## Framework mappings

Mappings use SKOS-style relationships:

- `exactMatch`
- `closeMatch`
- `broaderMatch`
- `narrowerMatch`
- `relatedMatch`

Mappings connect definitions without asserting that separately governed indicators are identical.
