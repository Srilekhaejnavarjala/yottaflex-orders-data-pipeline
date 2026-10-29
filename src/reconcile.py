"""Stage 8 - reconciliation.  Every check is an independent assertion; results are
reported (and a failing check aborts + rolls back the run)."""
from . import config


def reconcile(conn, counts: dict, before: dict) -> list:
    """Return a list of {check, expected, actual, passed}.  ``before`` = curated row counts
    taken at the start of the transaction."""
    q = lambda sql: conn.execute(sql).fetchone()[0]
    excluded = ",".join(f"'{s}'" for s in sorted(config.EXCLUDED_FROM_SALES))
    checks = []

    def add(name, expected, actual):
        checks.append({"check": name, "expected": expected, "actual": actual,
                       "passed": expected == actual})

    for e in ("customers", "orders"):
        add(f"{e}: input = accepted + rejected", counts[f"{e}_input"],
            counts[f"{e}_accepted"] + counts[f"{e}_rejected"])
        add(f"{e}: accepted = published + skipped_existing", counts[f"{e}_accepted"],
            counts[f"{e}_published"] + counts[f"{e}_skipped_existing"])
        add(f"{e}: curated rowcount = before + published", before[e] + counts[f"{e}_published"],
            q(f"SELECT COUNT(*) FROM {e}"))
    add("orders: accepted amount = published + skipped_existing amount (cents)",
        counts["orders_accepted_amount_cents"],
        counts["orders_published_amount_cents"] + counts["orders_skipped_amount_cents"])
    add("customers: no null/duplicate customer_id", 0,
        q("SELECT COUNT(*) - COUNT(DISTINCT customer_id) + SUM(customer_id IS NULL) FROM customers") or 0)
    add("orders: no null/duplicate order_id", 0,
        q("SELECT COUNT(*) - COUNT(DISTINCT order_id) + SUM(order_id IS NULL) FROM orders") or 0)
    add("orders: every order references a curated customer", 0,
        q("SELECT COUNT(*) FROM orders o LEFT JOIN customers c USING (customer_id) "
          "WHERE c.customer_id IS NULL"))
    add("daily_sales: order_count = eligible curated orders",
        q(f"SELECT COUNT(*) FROM orders WHERE status NOT IN ({excluded})"),
        q("SELECT COALESCE(SUM(order_count), 0) FROM daily_sales"))
    add("daily_sales: total_sales_cents = eligible curated order cents",
        q(f"SELECT COALESCE(SUM(amount_cents), 0) FROM orders WHERE status NOT IN ({excluded})"),
        q("SELECT COALESCE(SUM(total_sales_cents), 0) FROM daily_sales"))
    return checks