"""CSV export of the current asset-filter result set.

The filter/order query is owned by ``search.fetch_rows``; this module only
serialises those rows. Using the standard ``csv`` writer handles commas,
quotes and embedded newlines. A UTF-8 BOM is prepended so Chinese text opens
correctly in the spreadsheet applications commonly used by content operations.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone

from .db import get_conn

FIELDNAMES = ("uuid", "title", "description", "filename", "media_type", "tags", "created_at")
TAG_SEPARATOR = "; "


def _tags_by_asset(asset_ids: list[int]) -> dict[int, str]:
    if not asset_ids:
        return {}
    placeholders = ",".join("?" for _ in asset_ids)
    rows = get_conn().execute(
        f"SELECT at.asset_id, t.name FROM asset_tags at "
        f"JOIN tags t ON t.id = at.tag_id "
        f"WHERE at.asset_id IN ({placeholders}) ORDER BY at.asset_id, t.name",
        asset_ids,
    ).fetchall()
    collected: dict[int, list[str]] = defaultdict(list)
    for row in rows:
        collected[row["asset_id"]].append(row["name"])
    return {aid: TAG_SEPARATOR.join(names) for aid, names in collected.items()}


def tags_cell(row: dict) -> str:
    """Single-row helper, useful in tests and callers without a row batch."""
    return _tags_by_asset([row["id"]]).get(row["id"], "")


def build_csv(rows: list[dict]) -> str:
    """Return a complete CSV document (including header and BOM).

    Zero rows still produce the header line. Values are kept verbatim: no
    formula neutralisation, so spreadsheet-safe opening remains the caller's
    responsibility for untrusted metadata.
    """
    tags = _tags_by_asset([row["id"] for row in rows])
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(FIELDNAMES)
    for row in rows:
        writer.writerow([
            row.get("uuid") or "",
            row.get("title") or "",
            row.get("description") or "",
            row.get("filename") or "",
            row.get("media_type") or "",
            tags.get(row["id"], ""),
            row.get("created_at") or "",
        ])
    return "\ufeff" + buf.getvalue()


def download_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    return f"keepstack-assets-{stamp}.csv"
