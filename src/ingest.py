"""Stage 1 - ingest: read a CSV while keeping the physical line number of every record.

We read with the stdlib ``csv`` module first (not ``pd.read_csv``) because pandas either
raises on, or silently pads/truncates, rows with the wrong number of fields.  Reading
raw records lets us quarantine a malformed row and still process the valid rows after it.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class SchemaError(Exception):
    """Whole-file failure: the file cannot be parsed safely.  The run fails."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass
class RawFile:
    path: Path
    header: list          # normalised (trimmed, lower-cased) header names
    records: list         # [(source_row, [fields...]), ...]  data rows only


def read_raw(path) -> RawFile:
    path = Path(path)
    if not path.is_file():
        raise SchemaError("input_file_not_found", f"{path} does not exist")
    records = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise SchemaError("missing_required_column", f"{path.name} is empty (no header row)")
        prev = reader.line_num
        for fields in reader:
            start_line = prev + 1          # first physical line of this record
            prev = reader.line_num
            if not fields:                 # blank line: not a record
                continue
            records.append((start_line, fields))
    return RawFile(path, [h.strip().lower() for h in header], records)


def check_schema(raw: RawFile, required: list) -> None:
    """Strict contract: exactly the required columns, no duplicates, no extras."""
    header = raw.header
    dupes = sorted({h for h in header if header.count(h) > 1})
    if dupes:
        raise SchemaError("unexpected_schema", f"{raw.path.name}: duplicate columns {dupes}")
    missing = [c for c in required if c not in header]
    if missing:
        raise SchemaError("missing_required_column", f"{raw.path.name}: missing columns {missing}")
    extra = [c for c in header if c not in required]
    if extra:
        raise SchemaError("unexpected_schema", f"{raw.path.name}: unexpected columns {extra}")


def to_frame(raw: RawFile):
    """Split records into a well-formed DataFrame and a list of malformed rejects.

    Returns (frame, malformed) where frame has all-string columns plus ``source_row`` and
    malformed is a list of dicts {source_row, rejection_reason, payload}.
    """
    width = len(raw.header)
    good_rows, good_lines, malformed = [], [], []
    for line, fields in raw.records:
        if len(fields) == width:
            good_rows.append(fields)
            good_lines.append(line)
        else:
            malformed.append({"source_row": line, "rejection_reason": "malformed_row",
                              "payload": fields})
    frame = pd.DataFrame(good_rows, columns=raw.header, dtype="string")
    frame.insert(0, "source_row", pd.Series(good_lines, dtype="int64"))
    return frame, malformed