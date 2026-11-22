"""CSV export of the current asset-filter result set.

The filter/order query is owned by ``search``; this module only serialises
those rows. Rows arrive in batches from ``search.iter_rows`` so a large result
set is never fully materialised. The standard ``csv`` writer handles commas,
quotes and embedded newlines. A UTF-8 BOM is prepended so Chinese text opens
correctly in the spreadsheet applications commonly used by content operations.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from .search import tags_by_asset

FIELDNAMES = ("uuid", "title", "description", "filename", "media_type", "tags", "created_at")
TAG_SEPARATOR = "; "
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def neutralise_formula(value) -> str:
    """Prefix spreadsheet formula triggers with an apostrophe.

    The raw text remains present after the marker, so the export is still
    readable; the trade-off is that such cells no longer evaluate on open.
    """
    text = "" if value is None else str(value)
    if text.lstrip().startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _row_values(row: dict, neutralise: bool = True) -> list[str]:
    tags = row.get("tags")
    if tags is None:
        tags = tags_by_asset([row["id"]]).get(row["id"], [])
    cell = tags if isinstance(tags, str) else TAG_SEPARATOR.join(sorted(tags))
    values = [
        row.get("uuid") or "",
        row.get("title") or "",
        row.get("description") or "",
        row.get("filename") or "",
        row.get("media_type") or "",
        cell,
        row.get("created_at") or "",
    ]
    return [neutralise_formula(v) for v in values] if neutralise else values


def _csv_line(values) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(list(values))
    return buf.getvalue()


def iter_csv(rows, neutralise: bool = True):
    """Yield a BOM, the header, then one correctly quoted line per row."""
    yield "\ufeff"
    yield _csv_line(FIELDNAMES)
    for row in rows:
        yield _csv_line(_row_values(row, neutralise=neutralise))


def build_csv(rows: list[dict], neutralise: bool = True) -> str:
    """Convenience wrapper for callers/tests that already hold all rows."""
    return "".join(iter_csv(rows, neutralise=neutralise))


def download_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    return f"keepstack-assets-{stamp}.csv"
