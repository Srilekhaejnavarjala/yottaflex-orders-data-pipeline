"""Orchestrates the batch run:  ingest -> validate -> transform -> publish -> reconcile.

Usage:
    python -m src.pipeline                       # runs on data/input/*.csv
    python -m src.pipeline --customers C --orders O --db DB --reporting-tz Asia/Kolkata
Exit code: 0 on success, 1 on a failed run (the failure is still recorded in pipeline_runs).
"""
import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config, ingest, load, reconcile, transform, validate

log = logging.getLogger("pipeline")


class ReconciliationError(Exception):
    pass


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _empty_counts() -> dict:
    return {c: 0 for c in load.COUNT_COLUMNS}


def run_pipeline(customers_path=config.DEFAULT_CUSTOMERS, orders_path=config.DEFAULT_ORDERS,
                 db_path=config.DEFAULT_DB, output_dir=config.DEFAULT_OUTPUT_DIR,
                 run_id=None, reporting_tz=config.DEFAULT_REPORTING_TZ) -> dict:
    """Run one batch.  Never raises for data/runtime problems: returns the run report."""
    run_id = run_id or new_run_id()
    t0 = time.perf_counter()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = load.connect(db_path)
    load.start_run(conn, run_id, customers_path, orders_path, reporting_tz)
    counts, stages = _empty_counts(), {}
    stage, checks, all_rejects = "init", [], []
    status, failure = "success", None
    cust_name, ord_name = Path(customers_path).name, Path(orders_path).name

    def timed(name):
        nonlocal stage
        stage = name
        log.info("run %s: stage=%s", run_id, name)
        return time.perf_counter()

    try:
        # ---- ingest + schema ------------------------------------------------
        t = timed("ingest")
        raw_c, raw_o = ingest.read_raw(customers_path), ingest.read_raw(orders_path)
        stages["ingest"] = time.perf_counter() - t
        t = timed("validate_schema")
        ingest.check_schema(raw_c, config.CUSTOMER_COLUMNS)
        ingest.check_schema(raw_o, config.ORDER_COLUMNS)
        frame_c, malformed_c = ingest.to_frame(raw_c)
        frame_o, malformed_o = ingest.to_frame(raw_o)
        counts["customers_input"] = len(frame_c) + len(malformed_c)
        counts["orders_input"] = len(frame_o) + len(malformed_o)
        stages["validate_schema"] = time.perf_counter() - t

        # ---- everything below is ONE transaction: publish all or nothing -----
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = {"customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
                      "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]}

            # customers
            t = timed("validate_customers")
            valid_c, rej_c = validate.validate_customers(frame_c, config.CUSTOMER_COLUMNS)
            stages["validate_customers"] = time.perf_counter() - t
            t = timed("transform_customers")
            cur_c = transform.transform_customers(valid_c, run_id, cust_name)
            existing_c = load.read_table(conn, "customers")
            new_c, same_c, conflict_c = load.plan_publish(
                cur_c, existing_c, "customer_id", ["customer_name", "email", "created_at"])
            rej_c = _add_conflicts(rej_c, conflict_c, frame_c, config.CUSTOMER_COLUMNS,
                                   "conflicts_with_published_customer")
            stages["transform_customers"] = time.perf_counter() - t

            # orders reference customers loaded now OR in an earlier run
            known = set(existing_c["customer_id"]) | set(cur_c["customer_id"])
            t = timed("validate_orders")
            valid_o, rej_o = validate.validate_orders(frame_o, config.ORDER_COLUMNS, known)
            stages["validate_orders"] = time.perf_counter() - t
            t = timed("transform_orders")
            cur_o = transform.transform_orders(valid_o, run_id, ord_name, reporting_tz)
            existing_o = load.read_table(conn, "orders")
            new_o, same_o, conflict_o = load.plan_publish(
                cur_o, existing_o, "order_id",
                ["customer_id", "order_timestamp", "order_date", "amount_cents", "status"])
            rej_o = _add_conflicts(rej_o, conflict_o, frame_o, config.ORDER_COLUMNS,
                                   "conflicts_with_published_order")
            stages["transform_orders"] = time.perf_counter() - t

            # rejects (+ malformed rows from ingest)
            rej_c = _with_malformed(rej_c, malformed_c, config.CUSTOMER_COLUMNS)
            rej_o = _with_malformed(rej_o, malformed_o, config.ORDER_COLUMNS)

            counts.update(
                customers_rejected=len(rej_c), customers_accepted=len(new_c) + len(same_c),
                customers_skipped_existing=len(same_c),
                orders_rejected=len(rej_o), orders_accepted=len(new_o) + len(same_o),
                orders_skipped_existing=len(same_o),
                orders_accepted_amount_cents=int(new_o["amount_cents"].sum() + same_o["amount_cents"].sum()),
                orders_skipped_amount_cents=int(same_o["amount_cents"].sum()))

            # publish
            t = timed("publish")
            load.insert_rejects(conn, run_id, "customers", cust_name, rej_c)
            load.insert_rejects(conn, run_id, "orders", ord_name, rej_o)
            counts["customers_published"] = load.insert_rows(conn, "customers", new_c)
            counts["orders_published"] = load.insert_rows(conn, "orders", new_o)
            counts["orders_published_amount_cents"] = int(new_o["amount_cents"].sum())
            load.rebuild_daily_sales(conn)
            stages["publish"] = time.perf_counter() - t

            # reconcile (inside the transaction: a failed check rolls everything back)
            t = timed("reconcile")
            checks = reconcile.reconcile(conn, counts, before)
            stages["reconcile"] = time.perf_counter() - t
            failed = [c for c in checks if not c["passed"]]
            if failed:
                raise ReconciliationError(f"{len(failed)} reconciliation check(s) failed: "
                                          + "; ".join(c["check"] for c in failed))
            conn.execute("COMMIT")
            all_rejects = [(cust_name, "customers", rej_c), (ord_name, "orders", rej_o)]
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    except Exception as exc:                          # recorded, not swallowed
        status = "failed"
        reason = getattr(exc, "reason", type(exc).__name__)
        failure = {"failed_stage": stage, "failure_reason": reason, "failure_detail": str(exc)}
        log.error("run %s FAILED at stage=%s reason=%s: %s", run_id, stage, reason, exc)
        counts = {k: (0 if k.endswith(("published", "published_amount_cents")) else v)
                  for k, v in counts.items()}       # rolled back: nothing was published

    duration = round(time.perf_counter() - t0, 4)
    load.finish_run(conn, run_id, status, duration, counts, **(failure or {}))
    report = _build_report(conn, run_id, status, duration, counts, stages, checks, failure,
                           customers_path, orders_path, reporting_tz)
    conn.close()
    _write_outputs(output_dir, run_id, report, all_rejects)
    log.info("run %s finished: status=%s duration=%.3fs", run_id, status, duration)
    return report


def _add_conflicts(rejects, conflicts, frame, columns, reason):
    """Rows that clash with an already-published key but carry different content."""
    if conflicts.empty:
        return rejects
    originals = frame[frame["source_row"].isin(conflicts["source_row"])]
    extra = pd.DataFrame({
        "source_row": originals["source_row"].astype("int64"),
        "rejection_reason": reason,
        "payload": validate.payload_json(originals, columns)})
    return pd.concat([rejects, extra], ignore_index=True)


def _with_malformed(rejects, malformed, columns):
    if not malformed:
        return rejects.sort_values("source_row").reset_index(drop=True)
    extra = pd.DataFrame({
        "source_row": [m["source_row"] for m in malformed],
        "rejection_reason": "malformed_row",
        "payload": [json.dumps({"raw_fields": m["payload"], "expected_columns": columns},
                               ensure_ascii=False) for m in malformed]})
    return pd.concat([rejects, extra]).sort_values("source_row").reset_index(drop=True)


def _build_report(conn, run_id, status, duration, counts, stages, checks, failure,
                  customers_path, orders_path, reporting_tz) -> dict:
    total_cents = conn.execute(
        "SELECT COALESCE(SUM(total_sales_cents), 0) FROM daily_sales").fetchone()[0]
    reasons = {}
    for ent, reason, n in conn.execute(
            "SELECT entity, rejection_reason, COUNT(*) FROM rejected_records WHERE run_id=? "
            "GROUP BY 1, 2 ORDER BY 1, 2", (run_id,)):
        reasons.setdefault(ent, {})[reason] = n
    return {
        "run_id": run_id, "status": status, **(failure or {}),
        "customers_file": str(customers_path), "orders_file": str(orders_path),
        "reporting_tz": reporting_tz,
        **counts,
        "rejects_by_reason": reasons,
        "curated_total_sales": f"{total_cents / 100:.2f}",   # all curated, eligible statuses
        "duration_seconds": duration,
        "stage_seconds": {k: round(v, 4) for k, v in stages.items()},
        "reconciliation": checks,
    }


def _write_outputs(output_dir: Path, run_id: str, report: dict, all_rejects) -> None:
    text = json.dumps(report, indent=2)
    (output_dir / f"run_report_{run_id}.json").write_text(text)
    (output_dir / "latest_run_report.json").write_text(text)
    frames = []
    for fname, entity, rej in all_rejects:
        if len(rej):
            frames.append(rej.assign(run_id=run_id, entity=entity, source_file=fname))
    if frames:
        pd.concat(frames)[["run_id", "entity", "source_file", "source_row",
                           "rejection_reason", "payload"]].to_csv(
            output_dir / f"rejected_records_{run_id}.csv", index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--customers", default=config.DEFAULT_CUSTOMERS)
    ap.add_argument("--orders", default=config.DEFAULT_ORDERS)
    ap.add_argument("--db", default=config.DEFAULT_DB)
    ap.add_argument("--output-dir", default=config.DEFAULT_OUTPUT_DIR)
    ap.add_argument("--reporting-tz", default=config.DEFAULT_REPORTING_TZ)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    rep = run_pipeline(a.customers, a.orders, a.db, a.output_dir, reporting_tz=a.reporting_tz)
    keys = ["run_id", "status", "failed_stage", "failure_reason", "customers_input",
            "customers_accepted", "customers_rejected", "customers_published", "orders_input",
            "orders_accepted", "orders_rejected", "orders_published", "orders_skipped_existing",
            "curated_total_sales", "duration_seconds"]
    print("\n".join(f"{k}: {rep[k]}" for k in keys if k in rep))
    print("rejects_by_reason:", json.dumps(rep["rejects_by_reason"]))
    print("reconciliation:", "ALL PASSED" if rep["reconciliation"] and
          all(c["passed"] for c in rep["reconciliation"]) else "n/a / FAILED")
    return 0 if rep["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())