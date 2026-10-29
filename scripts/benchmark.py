
"""Benchmark the batch pipeline at several dataset sizes."""

import json
import subprocess
import sys
import time
from pathlib import Path

from generate_data import generate


ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "docs" / "performance_results.json"


def run_benchmark(customers_count: int, orders_count: int, seed: int = 42):
    work_dir = ROOT / "data" / "generated" / f"benchmark_{customers_count}_{orders_count}"
    input_dir = work_dir / "input"
    output_dir = work_dir / "output"
    db_path = work_dir / "benchmark.db"

    customers_path, orders_path = generate(
        customers_count, orders_count, input_dir, seed
    )

    command = [
        sys.executable,
        "-m",
        "src.pipeline",
        "--customers", str(customers_path),
        "--orders", str(orders_path),
        "--db", str(db_path),
        "--output-dir", str(output_dir),
        "--quiet",
    ]

    start = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(
            f"Benchmark failed for {customers_count} customers / "
            f"{orders_count} orders.\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    report_path = output_dir / "latest_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    return {
        "customers": customers_count,
        "orders": orders_count,
        "status": report.get("status"),
        "customers_published": report.get("customers_published"),
        "orders_published": report.get("orders_published"),
        "customers_rejected": report.get("customers_rejected"),
        "orders_rejected": report.get("orders_rejected"),
        "pipeline_duration_seconds": report.get("duration_seconds"),
        "wall_clock_seconds": round(elapsed, 4),
        "reconciliation": report.get("reconciliation"),
        "return_code": result.returncode,
    }


def main():
    sizes = [
        (100, 500),
        (1000, 5000),
        (5000, 25000),
    ]

    results = []
    for customers_count, orders_count in sizes:
        print(f"Benchmarking {customers_count} customers, {orders_count} orders...")
        result = run_benchmark(customers_count, orders_count)
        results.append(result)
        print(
            f"  status={result['status']}, "
            f"pipeline={result['pipeline_duration_seconds']}s, "
            f"wall_clock={result['wall_clock_seconds']}s"
        )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "environment": {
                    "python_version": sys.version.split()[0],
                    "platform": sys.platform,
                    "note": (
                        "Single run per size; timings are observational, "
                        "not a production capacity guarantee."
                    ),
                },
                "results": results,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"\nSaved benchmark results to: {RESULTS_PATH}")
    print("Review docs/performance_results.json before committing it.")


if __name__ == "__main__":
    main()
