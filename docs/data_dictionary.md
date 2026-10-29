# Data Dictionary

## 1. Overview

The pipeline ingests customer and order records from CSV files. It cleans field whitespace, validates records, transforms valid data, and publishes curated records to SQLite. Rejected records retain their source row number, rejection reason, and original row payload.

The configured input schemas are strict: required columns must be present, and unexpected columns cause a schema validation failure. Column order does not matter, and header names are trimmed and lower-cased.

## 2. Customer Input — `customers.csv`

Required columns:

| Column | Purpose | Validation and handling |
|---|---|---|
| `customer_id` | Customer identifier and primary key | Required; blank or null values are rejected as `null_primary_key`. |
| `customer_name` | Customer name | Required; blank or null values are rejected as `missing_customer_name`. |
| `email` | Customer email address | If provided, must match the configured basic email pattern; otherwise rejected as `invalid_email`. |
| `created_at` | Customer creation timestamp | If provided, must parse as an ISO 8601 timestamp; otherwise rejected as `invalid_timestamp`. |

### Customer validation rules

- Leading and trailing whitespace is removed from field values; blank strings become missing values.
- Timestamps are parsed and normalized to UTC.
- The first valid occurrence of a `customer_id` wins. Later valid duplicates are rejected as `duplicate_customer_id`.
- Each rejected row receives one rejection reason according to the validation precedence implemented in `src/validate.py`.

Customer rejection reasons include:

- `null_primary_key`
- `missing_customer_name`
- `invalid_email`
- `invalid_timestamp`
- `duplicate_customer_id`
- `malformed_row` (handled by the ingestion/pipeline stages)

## 3. Order Input — `orders.csv`

Required columns:

| Column | Purpose | Validation and handling |
|---|---|---|
| `order_id` | Order identifier and primary key | Required; blank or null values are rejected as `null_primary_key`. |
| `customer_id` | Customer associated with the order | Required; blank or null values are rejected as `null_customer_id`. Must reference a known customer or be rejected as `unknown_customer_id`. |
| `order_timestamp` | Time the order occurred | Must parse as an ISO 8601 timestamp; parsed timestamps are normalized to UTC. Invalid values are rejected as `invalid_timestamp`. |
| `amount` | Monetary amount | Must be a positive numeric amount with up to two decimal places and no sign or exponent notation. Values exceeding the configured maximum are rejected as `invalid_amount`. |
| `status` | Order lifecycle status | Case-insensitive; must be one of the allowed statuses listed below. Invalid values are rejected as `invalid_status`. |

### Allowed order statuses

The configured values are:

- `placed`
- `paid`
- `shipped`
- `delivered`
- `cancelled`
- `refunded`

Status values are converted to lowercase during validation.

### Amount handling

Amounts are converted to integer cents to avoid using floating-point values as the stored monetary representation. The configured maximum amount is `100,000,000.00`.

Orders with zero, negative, malformed, or over-limit amounts are rejected.

### Order validation rules

- Field whitespace is trimmed and blank strings become missing values.
- Order timestamps are parsed and normalized to UTC.
- The customer identifier must exist among the known customer records available to the pipeline.
- The first valid occurrence of an `order_id` wins. Later valid duplicates are rejected as `duplicate_order_id`.
- Each rejected row receives one rejection reason according to the validation precedence implemented in `src/validate.py`.

Order rejection reasons include:

- `null_primary_key`
- `null_customer_id`
- `invalid_amount`
- `invalid_timestamp`
- `invalid_status`
- `unknown_customer_id`
- `duplicate_order_id`
- `malformed_row` (handled by the ingestion/pipeline stages)

## 4. Rejected Record Structure

Rejected records contain the following fields:

| Field | Description |
|---|---|
| `source_row` | Source row number tracked by ingestion |
| `rejection_reason` | First validation or ingestion rejection reason assigned |
| `payload` | JSON representation of the original source row values |

The pipeline writes rejected-record outputs to the configured output directory.

## 5. Curated Data and Reporting

The pipeline publishes accepted customer and order records to SQLite and derives a daily sales table. The exact curated table columns, primary keys, sales aggregation rules, and reporting-time-zone behavior are defined by the transformation and loading modules.

Run reports include processing counts, rejection summaries, timing information, and reconciliation results.

## 6. Source of Truth

The schema and validation behavior documented here are based on:

- `src/config.py`
- `src/validate.py`
- `src/ingest.py`
- `src/transform.py`
- `src/load.py`
- `src/reconcile.py`

If implementation behavior changes, update this document and the automated tests together.