import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_C = ROOT / "data" / "input" / "customers.csv"
SAMPLE_O = ROOT / "data" / "input" / "orders.csv"
EXPECTED = json.loads((ROOT / "tests" / "expected" / "sample_expected.json").read_text())

C_HEADER = "customer_id,customer_name,email,created_at\n"
O_HEADER = "order_id,customer_id,order_timestamp,amount,status\n"


@pytest.fixture
def env(tmp_path):
    """Helper bundle: temp db/output dir plus ``write`` and ``run`` shortcuts."""
    from src.pipeline import run_pipeline

    class Env:
        db = tmp_path / "wh.db"
        out = tmp_path / "out"

        def write(self, name, text):
            p = tmp_path / name
            p.write_text(text)
            return p

        def run(self, customers=SAMPLE_C, orders=SAMPLE_O, **kw):
            return run_pipeline(customers, orders, self.db, self.out, **kw)

        def q(self, sql, args=()):
            conn = sqlite3.connect(self.db)
            try:
                return conn.execute(sql, args).fetchall()
            finally:
                conn.close()

        def count(self, table):
            return self.q(f"SELECT COUNT(*) FROM {table}")[0][0]

    return Env()