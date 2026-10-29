"""Central configuration: schemas, allowed values and business-rule constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CUSTOMERS = ROOT / "data" / "input" / "customers.csv"
DEFAULT_ORDERS = ROOT / "data" / "input" / "orders.csv"
DEFAULT_DB = ROOT / "data" / "output" / "warehouse.db"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "output"

# Strict source contract: a file must contain exactly these columns
# (any order, header names are trimmed and lower-cased).
CUSTOMER_COLUMNS = ["customer_id", "customer_name", "email", "created_at"]
ORDER_COLUMNS = ["order_id", "customer_id", "order_timestamp", "amount", "status"]

ALLOWED_STATUSES = {"placed", "paid", "shipped", "delivered", "cancelled", "refunded"}
# Orders in these statuses are published but do NOT count towards daily_sales.
EXCLUDED_FROM_SALES = {"cancelled", "refunded"}

MAX_AMOUNT_CENTS = 100_000_000_00  # 100,000,000.00 sanity ceiling

# Timestamps are stored in UTC; order_date is derived in this reporting timezone.
DEFAULT_REPORTING_TZ = "UTC"