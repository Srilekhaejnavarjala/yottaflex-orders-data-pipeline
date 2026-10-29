
"""Generate reproducible customer and order CSV files for pipeline testing.

Example:
    py scripts/generate_data.py --customers 1000 --orders 5000 --output-dir data/generated/bench
"""
import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate(customers_count: int, orders_count: int, output_dir: Path, seed: int = 42):
    if customers_count < 1:
        raise ValueError("customers must be at least 1")
    if orders_count < 0:
        raise ValueError("orders cannot be negative")

    output_dir.mkdir(parents=True, exist_ok=True)
    customers_path = output_dir / "customers.csv"
    orders_path = output_dir / "orders.csv"
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with customers_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["customer_id", "customer_name", "email", "created_at"])
        for i in range(1, customers_count + 1):
            created = start + timedelta(minutes=i)
            writer.writerow([
                f"C{i:08d}",
                f"Customer {i}",
                f"customer{i}@example.com",
                created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ])

    with orders_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "customer_id", "order_timestamp", "amount", "status"])
        for i in range(1, orders_count + 1):
            customer_id = f"C{rng.randint(1, customers_count):08d}"
            timestamp = start + timedelta(minutes=i)
            amount = f"{rng.randint(100, 100000) / 100:.2f}"
            writer.writerow([
                f"O{i:010d}",
                customer_id,
                timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                amount,
                "paid",
            ])

    return customers_path, orders_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customers", type=int, default=1000)
    parser.add_argument("--orders", type=int, default=5000)
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated/bench"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    customers_path, orders_path = generate(
        args.customers, args.orders, args.output_dir, args.seed
    )
    print(f"Generated customers: {customers_path} ({args.customers} rows)")
    print(f"Generated orders: {orders_path} ({args.orders} rows)")
    print(f"Random seed: {args.seed}")


if __name__ == "__main__":
    main()
