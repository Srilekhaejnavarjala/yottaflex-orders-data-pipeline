"""Stage 5 - deterministic transformations of rows that already passed validation."""
import pandas as pd


def _iso_utc(series: pd.Series) -> pd.Series:
    return series.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def transform_customers(valid: pd.DataFrame, run_id: str, source_file: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "customer_id": valid["customer_id"].astype(object),
        "customer_name": valid["customer_name"].astype(object),
        "email": valid["email"].str.lower().astype(object),
        "created_at": _iso_utc(valid["created_at_utc"]).astype(object),
        "source_file": source_file,
        "source_row": valid["source_row"].astype("int64"),
        "run_id": run_id,
    })
    return out.astype(object).where(out.notna(), None)


def transform_orders(valid: pd.DataFrame, run_id: str, source_file: str,
                     reporting_tz: str) -> pd.DataFrame:
    ts = valid["order_ts_utc"]
    out = pd.DataFrame({
        "order_id": valid["order_id"].astype(object),
        "customer_id": valid["customer_id"].astype(object),
        "order_timestamp": _iso_utc(ts).astype(object),
        # calendar date in the reporting timezone (documented policy)
        "order_date": ts.dt.tz_convert(reporting_tz).dt.strftime("%Y-%m-%d").astype(object),
        "amount_cents": valid["amount_cents"].astype("int64"),
        "status": valid["status"].astype(object),
        "source_file": source_file,
        "source_row": valid["source_row"].astype("int64"),
        "run_id": run_id,
    })
    return out