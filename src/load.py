"""Stage 6/7 - publish to SQLite, audit trail, daily_sales, reconciliation queries."""
import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from . import config

# Count columns recorded for every run (also used to build the pipeline_runs DDL).
COUNT_COLUMNS = [
    f"{e}_{k}" for e in ("customers", "orders")
    for k in ("input", "accepted", "rejected", "published", "skipped_existing")
] + ["orders_accepted_amount_cents", "orders_published_amount_cents", "orders_skipped_amount_cents"]

DDL = f"""
CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY CHECK (length(customer_id) > 0),
    customer_name TEXT NOT NULL,
    email         TEXT,
    created_at    TEXT,
    source_file   TEXT NOT NULL,
    source_row    INTEGER NOT NULL,
    run_id        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY CHECK (length(order_id) > 0),
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    order_timestamp TEXT NOT NULL,
    order_date      TEXT NOT NULL,
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    status          TEXT NOT NULL,
    source_file     TEXT NOT NULL,
    source_row      INTEGER NOT NULL,
    run_id          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE TABLE IF NOT EXISTS daily_sales (
    order_date        TEXT PRIMARY KEY,
    order_count       INTEGER NOT NULL,
    total_sales_cents INTEGER NOT NULL,
    total_sales       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rejected_records (
    reject_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL,
    entity           TEXT NOT NULL,
    source_file      TEXT NOT NULL,
    source_row       INTEGER,
    rejection_reason TEXT NOT NULL,
    payload          TEXT,
    rejected_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rejects_run ON rejected_records(run_id);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    duration_seconds REAL,
    customers_file   TEXT,
    orders_file      TEXT,
    reporting_tz     TEXT,
    failed_stage     TEXT,
    failure_reason   TEXT,
    failure_detail   TEXT,
    {", ".join(f"{c} INTEGER" for c in COUNT_COLUMNS)}
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), isolation_level=None)   # explicit transactions
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    return conn


# ---- audit -----------------------------------------------------------------
def start_run(conn, run_id, customers_file, orders_file, reporting_tz):
    conn.execute(
        "INSERT INTO pipeline_runs (run_id, status, started_at, customers_file, orders_file, "
        "reporting_tz) VALUES (?, 'running', ?, ?, ?, ?)",
        (run_id, now_iso(), str(customers_file), str(orders_file), reporting_tz))


def finish_run(conn, run_id, status, duration, counts, failed_stage=None,
               failure_reason=None, failure_detail=None):
    cols = ", ".join(f"{c} = ?" for c in COUNT_COLUMNS)
    conn.execute(
        f"UPDATE pipeline_runs SET status=?, ended_at=?, duration_seconds=?, failed_stage=?, "
        f"failure_reason=?, failure_detail=?, {cols} WHERE run_id=?",
        (status, now_iso(), duration, failed_stage, failure_reason, failure_detail,
         *[counts.get(c) for c in COUNT_COLUMNS], run_id))


# ---- reads -----------------------------------------------------------------
def read_table(conn, table) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", conn)


# ---- idempotent publish planning --------------------------------------------
def plan_publish(new: pd.DataFrame, existing: pd.DataFrame, key: str, compare: list):
    """Split validated+transformed rows into (to_insert, skipped_identical, conflicts).

    * key not yet published                  -> insert
    * key published with identical content   -> skip (this is what makes reruns idempotent)
    * key published with DIFFERENT content   -> conflict; existing row wins, new row rejected
    """
    if existing.empty or new.empty:
        return new, new.iloc[0:0], new.iloc[0:0]
    merged = new.merge(existing[[key] + compare], on=key, how="left",
                       suffixes=("", "_old"), indicator=True)
    is_new = (merged["_merge"] == "left_only").to_numpy()
    same = pd.Series(True, index=merged.index)
    for c in compare:
        same &= (merged[c].astype(object).fillna("<NULL>") ==
                 merged[f"{c}_old"].astype(object).fillna("<NULL>"))
    same = same.to_numpy()
    new = new.reset_index(drop=True)
    return new[is_new], new[~is_new & same], new[~is_new & ~same]


def insert_rows(conn, table: str, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    cols = list(frame.columns)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    # Optimisation (measured in scripts/benchmark.py): one vectorised NaN->None conversion and
    # tolist(), instead of calling pd.isna() on every cell inside a Python generator.
    rows = frame.astype(object).where(frame.notna(), None).values.tolist()
    conn.executemany(sql, rows)
    return len(rows)


def insert_rejects(conn, run_id, entity, source_file, rejects: pd.DataFrame) -> None:
    if rejects.empty:
        return
    ts = now_iso()
    rows = [(run_id, entity, source_file, int(r.source_row), r.rejection_reason, r.payload, ts)
            for r in rejects.itertuples(index=False)]
    conn.executemany(
        "INSERT INTO rejected_records (run_id, entity, source_file, source_row, "
        "rejection_reason, payload, rejected_at) VALUES (?,?,?,?,?,?,?)", rows)


def rebuild_daily_sales(conn) -> None:
    """Full recompute from curated orders - makes late/backfilled data self-correcting."""
    excluded = ",".join(f"'{s}'" for s in sorted(config.EXCLUDED_FROM_SALES))
    conn.execute("DELETE FROM daily_sales")
    conn.execute(f"""
        INSERT INTO daily_sales (order_date, order_count, total_sales_cents, total_sales)
        SELECT order_date, COUNT(*), SUM(amount_cents), ROUND(SUM(amount_cents) / 100.0, 2)
        FROM orders WHERE status NOT IN ({excluded})
        GROUP BY order_date ORDER BY order_date""")