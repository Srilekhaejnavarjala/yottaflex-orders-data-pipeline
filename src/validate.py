"""Stage 2/3 - row-level validation.  Pure functions: DataFrame in, (valid, rejects) out.

Policy (documented in docs/design_decisions.md):
  * One rejection reason per row - the first failing rule in the precedence order below.
  * Duplicates: the FIRST VALID occurrence (file order) wins; later copies are rejected.
  * All checks are vectorised (no row-by-row Python loops).
"""
import json

import pandas as pd

from . import config

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
AMOUNT_RE = r"^\d{1,12}(\.\d{1,2})?$"      # non-negative, max 2 decimals, no sign/exponent


def _clean(series: pd.Series) -> pd.Series:
    """Trim whitespace; blank strings become NA."""
    s = series.str.strip()
    return s.mask(s == "")


def _assign(reason: pd.Series, mask: pd.Series, label: str) -> None:
    """Set ``label`` on rows that match ``mask`` and have no reason yet (precedence)."""
    reason[reason.isna() & mask.fillna(False)] = label


def payload_json(frame: pd.DataFrame, columns: list) -> pd.Series:
    """Original values of each row as a JSON string (for the reject record)."""
    records = frame[columns].astype(object).where(frame[columns].notna(), None).to_dict("records")
    return pd.Series([json.dumps(r, ensure_ascii=False) for r in records], index=frame.index)


def _split(frame, reason, columns):
    bad = frame[reason.notna()]
    rejects = pd.DataFrame({
        "source_row": bad["source_row"].astype("int64"),
        "rejection_reason": reason[bad.index],
        "payload": payload_json(bad, columns),
    })
    return rejects


def validate_customers(frame: pd.DataFrame, columns: list):
    """Return (valid_frame_with_clean_columns, rejects_frame)."""
    f = frame.copy()
    for c in columns:
        f[c] = _clean(f[c])
    created = pd.to_datetime(f["created_at"], utc=True, errors="coerce", format="ISO8601")
    reason = pd.Series(pd.NA, index=f.index, dtype="object")
    _assign(reason, f["customer_id"].isna(), "null_primary_key")
    _assign(reason, f["customer_name"].isna(), "missing_customer_name")
    _assign(reason, f["email"].notna() & ~f["email"].fillna("").str.match(EMAIL_RE),
            "invalid_email")
    _assign(reason, f["created_at"].notna() & created.isna(), "invalid_timestamp")
    # duplicates among otherwise-valid rows: first occurrence wins
    ok = reason.isna()
    dup = pd.Series(False, index=f.index)
    dup[ok] = f.loc[ok, "customer_id"].duplicated(keep="first")
    _assign(reason, dup, "duplicate_customer_id")

    rejects = _split(frame, reason, columns)
    valid = f[reason.isna()].copy()
    valid["created_at_utc"] = created[valid.index]
    return valid, rejects


def validate_orders(frame: pd.DataFrame, columns: list, known_customer_ids: set):
    """Return (valid_frame_with_clean_columns, rejects_frame)."""
    f = frame.copy()
    for c in columns:
        f[c] = _clean(f[c])
    ts = pd.to_datetime(f["order_timestamp"], utc=True, errors="coerce", format="ISO8601")
    amount_ok = f["amount"].fillna("").str.match(AMOUNT_RE)
    amount_num = pd.to_numeric(f["amount"].where(amount_ok), errors="coerce")
    cents = (amount_num * 100).round()
    status = f["status"].str.lower()

    reason = pd.Series(pd.NA, index=f.index, dtype="object")
    _assign(reason, f["order_id"].isna(), "null_primary_key")
    _assign(reason, f["customer_id"].isna(), "null_customer_id")
    _assign(reason, ~amount_ok | (cents <= 0) | (cents > config.MAX_AMOUNT_CENTS), "invalid_amount")
    _assign(reason, ts.isna(), "invalid_timestamp")
    _assign(reason, ~status.isin(config.ALLOWED_STATUSES), "invalid_status")
    _assign(reason, ~f["customer_id"].isin(known_customer_ids), "unknown_customer_id")
    ok = reason.isna()
    dup = pd.Series(False, index=f.index)
    dup[ok] = f.loc[ok, "order_id"].duplicated(keep="first")
    _assign(reason, dup, "duplicate_order_id")

    rejects = _split(frame, reason, columns)
    valid = f[reason.isna()].copy()
    valid["order_ts_utc"] = ts[valid.index]
    valid["amount_cents"] = cents[valid.index].astype("int64")
    valid["status"] = status[valid.index]
    return valid, rejects