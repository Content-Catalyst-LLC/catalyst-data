# Design Document

By Tariq Ahmad

Video overview: (Add your final YouTube URL here)

---

## Scope

Catalyst Data is a relational database designed to support **auditable, evidence-based analysis** across strategy, narrative, and sustainability domains. The database serves as the shared SQL backbone of the broader *Catalyst* suite, enabling structured measurement, provenance tracking, and cross-domain analysis.

Within the scope of this database are:

- **Entities**, representing countries, organizations, projects, or other units of analysis
- **Metrics**, representing quantitative indicators such as SDG measures, ESG indicators, or economic variables
- **Periods**, representing bounded time intervals over which measurements occur
- **Measurements**, representing observed values of metrics for entities during specific periods
- **Sources**, representing the provenance of measurements, including publishers and references

In addition, the database includes supporting tables intended to model:

- Design thinking artifacts such as experiments and hypotheses
- Narrative and contextual signals that may influence interpretation of quantitative data
- Legal and policy references that provide institutional context

Out of scope for this iteration are presentation layers such as dashboards or visualizations, as well as automated data ingestion pipelines. The database focuses exclusively on **data representation, integrity, and queryability**.

---

## Functional Requirements

This database supports the following functionality:

- Creating, reading, updating, and deleting entities, metrics, periods, and sources
- Recording quantitative measurements with explicit temporal and evidentiary context
- Tracing each measurement back to its source and associated confidence level
- Querying performance across entities, metrics, and periods
- Auditing data quality by identifying missing or incomplete provenance
- Supporting future extension into design, narrative, financial, and legal domains

At this stage, the database does not enforce domain-specific validation rules beyond referential integrity, nor does it implement access control or user authentication.

---

## Representation

Entities are captured in SQLite tables, normalized to reduce redundancy and enforce consistency through primary and foreign key constraints.

### Core Entities

The database includes the following core entities.

#### Entities

The `entities` table includes:

- `id`, which specifies the unique identifier for an entity as an `INTEGER`. This column has the `PRIMARY KEY` constraint applied.
- `name`, which specifies the human-readable name of the entity as `TEXT`.
- `entity_type`, which specifies the category of entity (e.g., country, organization, project) as `TEXT`.

All columns are required and therefore have the `NOT NULL` constraint applied.

#### Metrics

The `metrics` table includes:

- `id`, which specifies the unique identifier for a metric as an `INTEGER` with a `PRIMARY KEY` constraint.
- `name`, which specifies the metric’s name as `TEXT`.
- `unit`, which specifies the unit of measurement (e.g., percentage, index score) as `TEXT`.

All columns are required and have the `NOT NULL` constraint applied.

#### Periods

The `periods` table includes:

- `id`, which specifies the unique identifier for a period as an `INTEGER` with a `PRIMARY KEY` constraint.
- `label`, which provides a human-readable description of the period as `TEXT`.
- `start_date`, which specifies the beginning of the period as a `DATETIME`.
- `end_date`, which specifies the end of the period as a `DATETIME`.

All columns are required and therefore have the `NOT NULL` constraint applied.

#### Sources

The `sources` table includes:

- `id`, which specifies the unique identifier for a source as an `INTEGER` with a `PRIMARY KEY` constraint.
- `title`, which specifies the title of the source as `TEXT`.
- `url`, which specifies the reference URL for the source as `TEXT`.
- `publisher`, which specifies the publishing organization as `TEXT`.

All columns are required and have the `NOT NULL` constraint applied.

#### Measurements

The `measurements` table includes:

- `id`, which specifies the unique identifier for a measurement as an `INTEGER` with a `PRIMARY KEY` constraint.
- `entity_id`, which references the entity being measured as an `INTEGER` with a `FOREIGN KEY` constraint referencing `entities(id)`.
- `metric_id`, which references the metric being measured as an `INTEGER` with a `FOREIGN KEY` constraint referencing `metrics(id)`.
- `period_id`, which references the time period of the measurement as an `INTEGER` with a `FOREIGN KEY` constraint referencing `periods(id)`.
- `source_id`, which references the provenance of the measurement as an `INTEGER` with a `FOREIGN KEY` constraint referencing `sources(id)`.
- `value`, which specifies the measured value using a `NUMERIC` type affinity.
- `confidence_score`, which specifies a numeric confidence score associated with the measurement.

All foreign key columns enforce referential integrity, and all columns are required.

---

### Relationships

The following entity-relationship diagram illustrates the relationships among the core entities in the database.

![Catalyst Data ERD](erd.svg)

As shown in the diagram:

- One entity may have zero or many measurements, while each measurement is associated with exactly one entity.
- One metric may be associated with zero or many measurements, while each measurement quantifies exactly one metric.
- One period may contain zero or many measurements, while each measurement occurs during exactly one period.
- One source may support zero or many measurements, while each measurement references exactly one source.

This structure enables precise temporal and evidentiary tracing of all quantitative data.

---

## Optimizations

Given the expected usage patterns in `queries.sql`, indexes are created on commonly joined and filtered columns, including:

- Foreign key columns in the `measurements` table (`entity_id`, `metric_id`, `period_id`, `source_id`)
- Name-based lookup fields in the `entities` and `metrics` tables

These indexes improve performance for analytical queries that aggregate or compare measurements across entities, metrics, and time periods.

---

## Limitations

This schema assumes that each measurement has a single primary source and confidence score. More complex provenance models, such as multiple contributing sources or probabilistic uncertainty distributions, would require additional join tables and metadata.

Additionally, while extension tables for narrative, legal, and design-thinking contexts are included for future use, this iteration does not enforce semantic consistency between qualitative and quantitative domains beyond shared identifiers.