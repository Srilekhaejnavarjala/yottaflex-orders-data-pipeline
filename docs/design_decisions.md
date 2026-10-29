# Design Decisions

## 1. Pipeline Architecture

The project separates ingestion, validation, transformation, loading, reconciliation, and orchestration into individual Python modules.

- `ingest.py` reads source CSV files and handles input-level concerns.
- `validate.py` applies schema-independent row-level business rules.
- `transform.py` converts valid records into curated representations.
- `load.py` manages persistence and publication to SQLite.
- `reconcile.py` checks data consistency.
- `pipeline.py` coordinates the stages, records run information, and produces reports.
- `config.py` centralizes input paths, schemas, allowed statuses, and other constants.

**Reasoning:** Separating responsibilities makes the pipeline easier to test, debug, and maintain than implementing all behavior in one large function.

## 2. Strict Input Schema

The pipeline expects defined customer and order columns. Column order is flexible, and header names are normalized, but missing required columns or unexpected columns cause schema validation to fail.

**Reasoning:** A strict schema makes upstream data-contract changes visible rather than silently accepting potentially incompatible data.

**Trade-off:** An upstream source that adds a harmless column may require a deliberate schema update.

## 3. Row-Level Rejection Policy

Validation assigns one rejection reason per row. When multiple rules fail, the first applicable rule in the implemented precedence order determines the reported reason.

For duplicate identifiers, the first valid occurrence in file order wins; later valid duplicates are rejected.

**Reasoning:** Deterministic precedence makes rejection reports easier to interpret and keeps duplicate handling predictable.

**Trade-off:** A rejected row may have additional problems that are not reported because only the first failure is recorded.

## 4. Timestamp Normalization

Customer creation timestamps and order timestamps are parsed and normalized to UTC. The transformed timestamps are stored in a consistent UTC representation.

For orders, `order_date` is derived by converting the UTC timestamp to the configured reporting timezone before extracting the calendar date.

**Reasoning:** UTC provides a consistent timestamp representation across sources and offsets. Deriving reporting dates in an explicit timezone avoids treating every order as if it occurred on a UTC calendar date.

**Trade-off:** Daily sales totals can be grouped into different calendar dates when the reporting timezone changes. The chosen timezone must therefore be documented and applied consistently.

## 5. Monetary Precision

Order amounts are validated to allow at most two decimal places, then converted to integer cents for storage and calculations.

**Reasoning:** Integer minor units avoid common floating-point representation problems when working with monetary amounts.

**Trade-off:** Input formatting and precision rules must be explicit. Values with more than two decimal places are rejected rather than silently rounded.

## 6. Idempotency and Duplicate Handling

The pipeline checks existing curated records before publishing new records. Repeated inputs should not create duplicate curated records, and the implemented policy handles redelivery of existing identifiers.

**Reasoning:** Batch jobs are often rerun after failures or scheduled repeatedly. Repeated processing should not unintentionally duplicate previously published data.

**Trade-off:** A repeated record with changed content requires an explicit policy. The current automated tests cover the behavior when an existing order identifier is redelivered with changed content.

## 7. Transactional Publishing

The pipeline uses a SQLite transaction around publication and reconciliation. If the relevant processing or consistency checks fail, the transaction can be rolled back instead of leaving a partially published batch.

**Reasoning:** A batch should be published as a consistent unit rather than exposing only some of its related changes.

**Trade-off:** SQLite serializes writes, so concurrent writers may contend for the database. This approach is appropriate for a small local batch pipeline but may need reconsideration for higher-concurrency workloads.

## 8. Data Lineage and Run Auditing

Curated customer and order records retain the source filename, source row number, and run identifier. Run reports include execution status, counts, rejection summaries, timing information, and reconciliation results.

**Reasoning:** Lineage and audit information help explain where a record originated, which run processed it, and why a row was rejected.

**Trade-off:** Audit metadata and run reports consume storage and must be managed appropriately for long-running deployments.

## 9. SQLite as the Curated Store

SQLite provides a local relational database for curated records and derived sales data.

**Reasoning:** It is simple to run locally and supports transactions and relational constraints without requiring a separate database server.

**Trade-off:** A larger production deployment with multiple concurrent writers or distributed workloads may require a server-based database.

## 10. Testing and Reconciliation

The test suite covers normal sample processing, rejection reasons, schema failures, timezone behavior, duplicate handling, reruns, rollback and retry behavior, late-arriving orders, and reconciliation.

The pipeline also performs reconciliation checks as part of execution.

**Reasoning:** Successful execution alone does not establish data correctness. Tests and reconciliation provide separate checks on expected behavior and consistency.

## 11. Performance Measurement

Individual local execution times are not sufficient to establish scalability. Performance should be measured with controlled input sizes, repeatable runs, and documented environment details.

The benchmark script and performance results should contain measured values only; planned experiments must not be presented as completed measurements.

## 12. Known Limitations and Future Work

- Run performance tests at multiple input sizes and report repeatable measurements.
- Test behavior with larger and more varied datasets.
- Document operational requirements for scheduling, monitoring, retention, and deployment.
- Revisit database choice if concurrent writing or workload size exceeds the needs of a local batch pipeline.
## Performance Benchmark

### Environment
- Python: 3.14.3
- Platform: Windows (`win32`)
- Storage: SQLite
- Dataset: reproducibly generated customers and orders using seed `42`

### Results

| Customers | Orders | Pipeline duration (s) | Wall-clock duration (s) | Rejected rows | Result |
|---:|---:|---:|---:|---:|---|
| 100 | 500 | 0.3175 | 1.7789 | 0 | Success |
| 1,000 | 5,000 | 0.4670 | 1.8513 | 0 | Success |
| 5,000 | 25,000 | 0.8256 | 2.0711 | 0 | Success |

All reconciliation checks passed for each run, including input accounting, published row counts, key uniqueness, customer references, and daily-sales totals.

### Interpretation and Limitations

In these single-run measurements, pipeline-reported duration increased from 0.3175 seconds for 500 orders to 0.8256 seconds for 25,000 orders. Wall-clock duration includes process startup and other overhead.

These results demonstrate successful processing of the tested dataset sizes in this environment. They do not establish maximum throughput, production capacity, or performance under concurrent workloads. The benchmark uses valid generated inputs and does not measure performance under a high rejection rate or concurrent access.

For stronger performance evidence, repeat each dataset size several times, report median and range, and test larger datasets if the available environment permits.