"""Automated tests.  Expected answers live in tests/expected/ (never inside the inputs)."""
import json

from tests.conftest import C_HEADER, EXPECTED, O_HEADER


# ------------------------------------------------------------------ happy path (sample)
def test_sample_counts_match_hand_calculation(env):
    r = env.run()
    e = EXPECTED
    assert r["status"] == "success"
    for ent in ("customers", "orders"):
        assert r[f"{ent}_input"] == e[ent]["input"]
        assert r[f"{ent}_accepted"] == e[ent]["accepted"]
        assert r[f"{ent}_rejected"] == e[ent]["rejected"]
        assert r[f"{ent}_published"] == e[ent]["published"]
    assert r["orders_published_amount_cents"] == e["orders"]["published_amount_cents"]


def test_sample_published_keys_and_daily_sales(env):
    env.run()
    assert [x[0] for x in env.q("SELECT customer_id FROM customers ORDER BY 1")] == \
        EXPECTED["customers"]["published_ids"]
    assert [x[0] for x in env.q("SELECT order_id FROM orders ORDER BY 1")] == \
        EXPECTED["orders"]["published_ids"]
    got = [list(x) for x in env.q(
        "SELECT order_date, order_count, total_sales_cents FROM daily_sales ORDER BY 1")]
    assert got == EXPECTED["daily_sales_utc"]
    assert env.q("SELECT SUM(total_sales_cents) FROM daily_sales")[0][0] == EXPECTED["total_sales_cents"]


def test_every_reject_has_expected_reason_row_and_traceability(env):
    r = env.run()
    for ent in ("customers", "orders"):
        rows = env.q("SELECT source_row, rejection_reason, run_id, source_file, payload "
                     "FROM rejected_records WHERE entity=?", (ent,))
        got = {str(sr): reason for sr, reason, *_ in rows}
        assert got == EXPECTED[ent]["rejects_by_source_row"]
        for _, _, run_id, source_file, payload in rows:
            assert run_id == r["run_id"] and source_file.endswith(".csv")
            assert payload and json.loads(payload)          # original values preserved
    assert (env.out / f"rejected_records_{r['run_id']}.csv").exists()


def test_invariants_and_reconciliation_report(env):
    r = env.run()
    assert r["reconciliation"] and all(c["passed"] for c in r["reconciliation"])
    assert env.q("SELECT COUNT(*) FROM orders o LEFT JOIN customers c USING(customer_id) "
                 "WHERE c.customer_id IS NULL")[0][0] == 0
    assert env.count("customers") == env.q("SELECT COUNT(DISTINCT customer_id) FROM customers")[0][0]
    assert env.count("orders") == env.q("SELECT COUNT(DISTINCT order_id) FROM orders")[0][0]
    row = env.q("SELECT status, customers_input, orders_input, failed_stage FROM pipeline_runs")[0]
    assert row == ("success", 12, 19, None)


# ------------------------------------------------------------------ domain-specific cases
def test_cancelled_and_refunded_orders_published_but_excluded_from_sales(env):
    env.run()
    assert env.q("SELECT status FROM orders WHERE order_id IN ('O1005','O1007') ORDER BY 1") == \
        [("cancelled",), ("refunded",)]
    assert env.q("SELECT COUNT(*) FROM daily_sales WHERE order_date='2026-01-14'")[0][0] == 0


def test_zero_negative_and_non_numeric_amounts_rejected(env):
    env.run()
    reasons = dict(env.q("SELECT source_row, rejection_reason FROM rejected_records "
                         "WHERE entity='orders' AND source_row IN (9,10,11)"))
    assert set(reasons.values()) == {"invalid_amount"} and len(reasons) == 3


def test_near_midnight_offset_timestamp_and_reporting_timezone(env):
    env.run()   # default UTC: 2026-01-16T23:30-05:00 is 2026-01-17 in UTC
    assert env.q("SELECT order_timestamp, order_date FROM orders WHERE order_id='O1004'") == \
        [("2026-01-17T04:30:00Z", "2026-01-17")]


def test_reporting_timezone_changes_daily_buckets(env):
    r = env.run(reporting_tz="America/New_York")
    assert r["status"] == "success"
    got = [list(x) for x in env.q(
        "SELECT order_date, order_count, total_sales_cents FROM daily_sales ORDER BY 1")]
    assert got == EXPECTED["daily_sales_new_york"]


def test_customer_rejected_while_order_references_it(env):
    env.run()   # C006 is rejected (missing name) and O1013 references it
    assert env.q("SELECT rejection_reason FROM rejected_records "
                 "WHERE entity='orders' AND source_row=14") == [("unknown_customer_id",)]


def test_valid_row_after_malformed_row_is_still_processed(env):
    env.run()   # line 19 malformed, line 20 (O1018) valid
    assert env.q("SELECT amount_cents FROM orders WHERE order_id='O1018'") == [(4000,)]


# ------------------------------------------------------------------ edge cases from the brief
def test_empty_batch_header_only_is_a_successful_noop(env):
    c, o = env.write("c.csv", C_HEADER), env.write("o.csv", O_HEADER)
    r = env.run(c, o)
    assert r["status"] == "success"
    assert (r["customers_input"], r["orders_input"], r["orders_published"]) == (0, 0, 0)
    assert env.count("customers") == env.count("orders") == env.count("daily_sales") == 0
    assert env.q("SELECT status FROM pipeline_runs") == [("success",)]


def test_zero_byte_file_fails_clearly(env):
    r = env.run(env.write("c.csv", ""), env.write("o.csv", O_HEADER))
    assert r["status"] == "failed" and r["failure_reason"] == "missing_required_column"
    assert r["failed_stage"] == "ingest"


def test_missing_required_column_fails_and_publishes_nothing(env):
    bad = env.write("o.csv", "order_id,customer_id,order_timestamp,status\nO1,C001,2026-01-01T00:00:00Z,paid\n")
    r = env.run(orders=bad)
    assert r["status"] == "failed" and r["failure_reason"] == "missing_required_column"
    assert r["failed_stage"] == "validate_schema"
    assert env.count("customers") == 0 and env.count("orders") == 0
    assert env.q("SELECT status, failed_stage, failure_reason FROM pipeline_runs") == \
        [("failed", "validate_schema", "missing_required_column")]


def test_unexpected_schema_change_extra_column_fails(env):
    bad = env.write("o.csv", O_HEADER.strip() + ",coupon\nO1,C001,2026-01-01T00:00:00Z,5.00,paid,X\n")
    r = env.run(orders=bad)
    assert r["status"] == "failed" and r["failure_reason"] == "unexpected_schema"


def test_missing_input_file_fails_and_is_recorded(env):
    r = env.run(orders=env.db.parent / "nope.csv")
    assert r["status"] == "failed" and r["failure_reason"] == "input_file_not_found"
    assert env.count("pipeline_runs") == 1


def test_column_order_and_header_case_do_not_matter(env):
    c = env.write("c.csv", "Email, CUSTOMER_ID ,created_at,customer_name\nx@example.com,C1,2026-01-01,Xi\n")
    o = env.write("o.csv", "status,amount,order_timestamp,customer_id,order_id\npaid,5.5,2026-01-02T00:00:00Z,C1,O1\n")
    r = env.run(c, o)
    assert r["status"] == "success" and r["orders_published"] == 1
    assert env.q("SELECT amount_cents FROM orders") == [(550,)]


def test_duplicate_policy_first_valid_occurrence_wins(env):
    c = env.write("c.csv", C_HEADER + "C1,A,a@x.io,2026-01-01\nC1,B,b@x.io,2026-01-02\n")
    # first O1 has an invalid amount, so the SECOND (valid) O1 must win; third O1 is a dup
    o = env.write("o.csv", O_HEADER + "O1,C1,2026-01-01T00:00:00Z,abc,paid\n"
                  "O1,C1,2026-01-01T00:00:00Z,10.00,paid\nO1,C1,2026-01-01T00:00:00Z,99.00,paid\n")
    env.run(c, o)
    assert env.q("SELECT customer_name FROM customers") == [("A",)]
    assert env.q("SELECT amount_cents, source_row FROM orders") == [(1000, 3)]
    assert env.q("SELECT source_row, rejection_reason FROM rejected_records WHERE entity='orders' "
                 "ORDER BY 1") == [(2, "invalid_amount"), (4, "duplicate_order_id")]


# ------------------------------------------------------------------ idempotency / retry / history
def test_rerun_identical_input_creates_no_duplicates_and_keeps_audit_history(env):
    r1 = env.run()
    snapshot = (env.q("SELECT * FROM customers ORDER BY 1"), env.q("SELECT * FROM orders ORDER BY 1"),
                env.q("SELECT * FROM daily_sales ORDER BY 1"))
    r2 = env.run()
    assert r2["status"] == "success" and r1["run_id"] != r2["run_id"]
    assert (r2["customers_published"], r2["orders_published"]) == (0, 0)
    assert (r2["customers_skipped_existing"], r2["orders_skipped_existing"]) == (6, 8)
    assert (env.q("SELECT * FROM customers ORDER BY 1"), env.q("SELECT * FROM orders ORDER BY 1"),
            env.q("SELECT * FROM daily_sales ORDER BY 1")) == snapshot
    assert env.count("pipeline_runs") == 2                       # one audit row per execution
    assert env.count("rejected_records") == 2 * (6 + 11)         # reject history is per run
    assert all(c["passed"] for c in r2["reconciliation"])


def test_partial_failure_rolls_back_then_retry_succeeds(env, monkeypatch):
    from src import load
    real = load.insert_rows

    def boom(conn, table, frame):
        if table == "orders":                 # customers already inserted in the same txn
            raise RuntimeError("disk full (simulated)")
        return real(conn, table, frame)

    monkeypatch.setattr(load, "insert_rows", boom)
    r1 = env.run()
    assert r1["status"] == "failed" and r1["failed_stage"] == "publish"
    assert "disk full" in r1["failure_detail"]
    assert env.count("customers") == 0 and env.count("orders") == 0     # nothing half-published
    assert env.count("rejected_records") == 0 and env.count("daily_sales") == 0

    monkeypatch.setattr(load, "insert_rows", real)                       # operator fixes issue, retries
    r2 = env.run()
    assert r2["status"] == "success" and r2["orders_published"] == EXPECTED["orders"]["published"]
    assert env.q("SELECT status FROM pipeline_runs ORDER BY started_at") == [("failed",), ("success",)]


def test_late_arriving_order_recomputes_historic_daily_sales(env):
    env.run()
    late = env.write("o2.csv", O_HEADER + "O2000,C001,2026-01-15T01:00:00Z,10.00,paid\n")
    empty_c = env.write("c2.csv", C_HEADER)               # customers came in an earlier run
    r = env.run(empty_c, late)
    assert r["status"] == "success" and r["orders_published"] == 1
    assert env.q("SELECT order_count, total_sales_cents FROM daily_sales WHERE order_date='2026-01-15'") \
        == [(3, 16050)]                                    # 15050 + 1000, recomputed


def test_orders_may_reference_customers_published_in_an_earlier_run(env):
    env.run(env.write("c.csv", C_HEADER + "C1,A,a@x.io,2026-01-01\n"), env.write("o.csv", O_HEADER))
    r = env.run(env.write("c0.csv", C_HEADER),
                env.write("o2.csv", O_HEADER + "O1,C1,2026-01-02T00:00:00Z,5.00,paid\n"))
    assert r["orders_published"] == 1 and r["orders_rejected"] == 0


def test_redelivery_with_changed_content_is_rejected_existing_row_wins(env):
    env.run()
    changed = env.write("o2.csv", O_HEADER + "O1001,C001,2026-01-15T10:00:00Z,999.00,paid\n")
    r = env.run(env.write("c0.csv", C_HEADER), changed)
    assert r["status"] == "success" and r["orders_published"] == 0 and r["orders_rejected"] == 1
    assert env.q("SELECT amount_cents FROM orders WHERE order_id='O1001'") == [(10000,)]
    assert env.q("SELECT rejection_reason FROM rejected_records WHERE run_id=?", (r["run_id"],)) == \
        [("conflicts_with_published_order",)]