# Orders Data Pipeline

A Python-based batch data pipeline that ingests customer and order CSV files, validates their schemas and business rules, transforms valid records, publishes curated data to SQLite, quarantines rejected records, and checks data consistency.

## Key Features

- CSV ingestion and schema validation
- Customer and order business-rule validation
- Data transformation and curated SQLite tables
- Rejected-record output with rejection reasons
- Safe handling of repeated inputs and existing records
- Transactional publishing and rollback on failure
- Run reports with processing counts, timings, and reconciliation results
- Automated tests using pytest

## Technology Stack

- Python
- Pandas
- SQLite
- pytest

## Project Structure

```text
orders-data-pipeline/
├── data/
│   ├── input/
│   │   ├── customers.csv
│   │   └── orders.csv
│   └── output/
├── docs/
│   ├── data_dictionary.md
│   ├── design_decisions.md
│   └── performance_results.json
├── scripts/
│   ├── benchmark.py
│   └── generate_data.py
├── src/
│   ├── config.py
│   ├── ingest.py
│   ├── load.py
│   ├── pipeline.py
│   ├── reconcile.py
│   ├── transform.py
│   └── validate.py
├── tests/
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.14.3 (version used for local testing)
- pip

## Setup

Create and activate a virtual environment.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Run the Pipeline

From the repository root, run:

```powershell
py -m src.pipeline
```

The default input files are:

- `data/input/customers.csv`
- `data/input/orders.csv`

The pipeline uses SQLite for curated data storage. Run reports and rejected-record outputs are written to the configured output directory.

To see available command-line options, run:

```powershell
py -m src.pipeline --help
```

## Run Tests

Execute the automated test suite from the repository root:

```powershell
py -m pytest -v
```

The current test suite contains 22 passing tests, covering validation, malformed inputs, schema errors, reporting time zones, duplicate handling, reruns, rollback and retry behavior, and reconciliation.

## Current Validation Evidence

- The automated test suite passed: 22 tests.
- The pipeline completed successfully on the supplied sample CSV files.
- A repeated run completed successfully with the same processing counts and rejection reasons.
- Reconciliation checks passed on both observed runs.
- The observed execution times were approximately 0.24 seconds and 0.16 seconds on the local environment. These are sample runs, not a formal performance benchmark.

## Output and Data Handling

The pipeline writes curated data to SQLite and produces run reports and rejected-record outputs. Generated database files and run outputs are excluded from version control by `.gitignore`.

Keep source CSV files and documentation separate from generated artifacts. Do not commit virtual environments, local database files, or transient test outputs.

## Limitations and Future Improvements

- Performance should be measured across controlled input sizes and repeated trials before drawing scalability conclusions.
- Additional testing on larger datasets and representative production-like inputs would improve confidence.
- Operational deployment, monitoring, and scheduling are outside the currently verified local execution workflow.

## AI Assistance

Document the AI tools used, the prompts submitted, how suggestions were reviewed, and which implementation or testing decisions were made independently in `prompt_history.md`. Include only prompts that were actually used and describe AI contributions accurately.