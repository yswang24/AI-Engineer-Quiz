#!/usr/bin/env python3
"""Generate a deterministic catalog for the combined-filter assessment.

No binary fixtures are committed: every asset gets a tiny generated JPEG blob
and directly inserted catalog rows. Re-running the script removes and rebuilds
only rows whose uuid starts with ``fixture-``, leaving other data untouched.

Usage (from the repository root)::

    KEEPSTACK_DATA_DIR=/tmp/keepstack-demo python scripts/generate_fixture.py

Or let the script pick a directory::

    python scripts/generate_fixture.py --data-dir /tmp/keepstack-demo

It prints the collection ids and the expected combined-filter result, which
are also used by ``tests/test_filters_export.py``.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

os.environ.setdefault("KEEPSTACK_AI_ENABLED", "false")
os.environ.setdefault("KEEPSTACK_OCR_ENABLED", "false")

from keepstack import ingest, search, storage  # noqa: E402
from keepstack.auth import hash_password  # noqa: E402
from keepstack.audit import now_iso  # noqa: E402
from keepstack.config import config  # noqa: E402
from keepstack.db import get_conn, init_db, transaction  # noqa: E402

COLLECTIONS = {
    "campaigns": ("fixture-collection-campaigns", "Campaigns"),
    "internal": ("fixture-collection-internal", "Internal Ops"),
}

# Deliberately includes: mixed-case tags, a deleted asset, an asset missing
# one required tag, an internal-tagged asset, tied created_at values, and
# fields with Chinese characters, commas, quotes and embedded newlines.
ASSETS = [
    dict(uuid="fixture-001", title="Harbor master plan",
         description="Quay upgrade, phase 1", filename="harbor_master.jpg",
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-03-02T09:00:00Z", media_type="image"),
    dict(uuid="fixture-002", title="Harbor night photo",
         description="内部草稿, \"harbor\" 夜景\n第二行",
         filename="harbor夜景,草稿\"1.jpg",
         tags=("approved", "campaign", "internal"), collection="campaigns",
         created_at="2026-03-02T09:00:00Z", media_type="image"),
    dict(uuid="fixture-003", title="Harbor risk memo",
         description='Risk register, "high" priority\nneeds review',
         filename='harbor,risk "memo".txt',
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-03-02T09:00:00Z", media_type="document"),
    dict(uuid="fixture-004", title="Harbor press kit (uppercase tags)",
         description="Press images for harbor opening", filename="harbor_press.jpg",
         tags=("Approved", "CAMPAIGN"), collection="campaigns",
         created_at="2026-02-28T09:00:00Z", media_type="image"),
    dict(uuid="fixture-005", title="Harbor backlog",
         description="Only approved, not a campaign", filename="harbor_backlog.jpg",
         tags=("approved",), collection="campaigns",
         created_at="2026-02-27T09:00:00Z", media_type="image"),
    dict(uuid="fixture-006", title="Harbor internal note",
         description="Internal only", filename="harbor_internal.txt",
         tags=("approved", "campaign", "internal"), collection="internal",
         created_at="2026-02-26T09:00:00Z", media_type="document"),
    dict(uuid="fixture-007", title="Harbor archived copy",
         description="Deleted asset must not be returned", filename="harbor_archived.jpg",
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-02-25T09:00:00Z", media_type="image", status="deleted"),
    dict(uuid="fixture-008", title="Harbor duplicate filter input",
         description="Repeated include tags should not duplicate rows",
         filename="harbor_dup.jpg", tags=("approved", "campaign"),
         collection="campaigns", created_at="2026-02-24T09:00:00Z", media_type="image"),
    dict(uuid="fixture-009", title="Harbor oldest campaign",
         description="First created item", filename="harbor_oldest.jpg",
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-01-01T09:00:00Z", media_type="image"),
    dict(uuid="fixture-010", title="Harbor another same timestamp",
         description="Shows stable id tie-breaker", filename="harbor_tie.jpg",
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-03-02T09:00:00Z", media_type="image"),
    dict(uuid="fixture-011", title="Harbor CSV special characters",
         description='中文逗号, 双引号" 换行\n第二行',
         filename='harbor, "csv" 测试.txt',
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-02-20T09:00:00Z", media_type="document"),
    dict(uuid="fixture-012", title="Harbor campaign only",
         description="Missing approved", filename="harbor_campaign_only.jpg",
         tags=("campaign",), collection="campaigns",
         created_at="2026-02-19T09:00:00Z", media_type="image"),
    dict(uuid="fixture-013", title="Harbor (draft) [2026]",
         description="Punctuation should be safe in FTS", filename="harbor_draft.jpg",
         tags=("approved", "campaign"), collection="campaigns",
         created_at="2026-02-18T09:00:00Z", media_type="image"),
]

# Combined-filter scenario from README.md, after excluding internal/deleted/
# wrong-collection/missing-tag items: these six, oldest first.
EXPECTED_MATCHES = [
    "fixture-009", "fixture-013", "fixture-011", "fixture-008",
    "fixture-004", "fixture-001", "fixture-003", "fixture-010",
]


def _tiny_jpeg(index: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (40 + index * 7 % 200, 90, 160)).save(buf, format="JPEG")
    return buf.getvalue()


def build_fixture() -> dict:
    """Reset and rebuild the fixture set. Returns collection id mapping."""
    init_db()
    conn = get_conn()

    old_ids = [r["id"] for r in conn.execute("SELECT id FROM assets WHERE uuid LIKE 'fixture-%'")]
    with transaction() as conn:
        if old_ids:
            ph = ",".join("?" for _ in old_ids)
            for table in ("asset_tags", "asset_metadata", "asset_versions",
                          "asset_custom_values", "collection_assets"):
                conn.execute(f"DELETE FROM {table} WHERE asset_id IN ({ph})", old_ids)
            conn.execute(
                f"DELETE FROM share_links WHERE target_type = 'asset' AND target_id IN ({ph})", old_ids)
            conn.execute(f"DELETE FROM asset_fts WHERE rowid IN ({ph})", old_ids)
            conn.execute(f"DELETE FROM assets WHERE id IN ({ph})", old_ids)
        conn.execute("DELETE FROM collections WHERE uuid LIKE 'fixture-collection-%'")

        if not conn.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone():
            conn.execute(
                "INSERT INTO users (username, email, full_name, password_hash, role, is_active, created_at) "
                "VALUES ('admin','admin@example.org','Administrator',?,'admin',1,?)",
                (hash_password("admin"), now_iso()))

        collection_ids = {}
        for key, (uuid, name) in COLLECTIONS.items():
            cur = conn.execute(
                "INSERT INTO collections (uuid, name, description, kind, created_at) "
                "VALUES (?,?,?,'folder',?)", (uuid, name, "Quiz fixture", now_iso()))
            collection_ids[key] = cur.lastrowid

    for index, item in enumerate(ASSETS):
        sha, key, size = storage.store_bytes(_tiny_jpeg(index), "jpg")
        created = item["created_at"]
        with transaction() as conn:
            cur = conn.execute(
                "INSERT INTO assets (uuid, sha256, filename, mime_type, media_type, ext, size, "
                "title, description, status, storage_key, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item["uuid"], sha, item["filename"], "image/jpeg", item["media_type"], "jpg",
                 size, item["title"], item["description"], item.get("status", "active"),
                 key, created, created))
            asset_id = cur.lastrowid
            conn.execute(
                "INSERT INTO collection_assets (collection_id, asset_id, added_at) VALUES (?,?,?)",
                (collection_ids[item["collection"]], asset_id, created))
            for name in item["tags"]:
                conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
                tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]
                conn.execute(
                    "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id, source) VALUES (?,?,'manual')",
                    (asset_id, tag_id))
        ingest.reindex_fts(asset_id)

    return collection_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="Override KEEPSTACK_DATA_DIR for this run")
    args = parser.parse_args()
    if args.data_dir:
        config.data_dir = Path(args.data_dir).resolve()
        config.db_path = config.data_dir / "keepstack.db"
        config.blob_dir = config.data_dir / "blobs"
        config.thumb_dir = config.data_dir / "thumbnails"
        config.cache_dir = config.data_dir / "cache"
        import keepstack.db as db
        db._local.conn = None

    ids = build_fixture()
    result = search.search(q="harbor", collection_id=ids["campaigns"],
                           include_tags=["approved", "campaign"],
                           exclude_tags=["internal"], sort="oldest", limit=200)
    print(f"Generated {len(ASSETS)} fixture assets in {config.data_dir}")
    print(f"Campaigns collection id: {ids['campaigns']}")
    print(f"Combined-filter matches: {result['total']}")
    print("Oldest-first uuids: " + ", ".join(i["uuid"] for i in result["items"]))


if __name__ == "__main__":
    main()
