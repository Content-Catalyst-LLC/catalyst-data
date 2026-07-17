# Catalyst Data Demo

Version 1.5.0 emits the canonical `catalyst-data-record/1.0` structure in the browser.

Use shortcode:

```text
[catalyst_data_demo]
```

The demo does not send data to a server. It creates a local JSON record with stable semantic IDs, producer metadata, source provenance, structured method limitations, confidence, review readiness, and signal status.

The generated record now includes a complete `catalyst-data-observation-lineage/1.0` section with a research question, collection instrument, dataset, observation batch, baseline/current observations, and measurement transformation.
