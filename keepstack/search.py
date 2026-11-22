"""Search and discovery.

Three complementary modes over one catalog:

  * keyword  - FTS5 full-text across title, description, tags, metadata
  * filter   - faceted structured filters (media type, tag, status, dates)
  * semantic - embedding cosine ranking ("natural language" / more-like-this)

The keyword path also powers the quiz's combined-filter list and CSV export.
Both callers share :func:`build_where` and :func:`fetch_rows`, so pagination,
total counts and the exported set cannot drift apart.

Every ORDER BY has a unique id tie-breaker. Without it SQLite may return rows
with identical created_at in a different order between the count/page queries
(or between two requests), which causes duplicates/missing items on page turns.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from . import ai
from .db import get_conn

SORTS = {
    "newest": "a.created_at DESC, a.id DESC",
    "oldest": "a.created_at ASC, a.id ASC",
    "name": "a.title COLLATE NOCASE ASC, a.id ASC",
    "largest": "a.size DESC, a.id DESC",
}
DEFAULT_SORT = "newest"

# Legacy single-tag filter is kept for API compatibility; it has the same
# semantics as one entry in include_tags.
_INCLUDE_TAG_SQL = ("EXISTS (SELECT 1 FROM asset_tags at JOIN tags t ON t.id = at.tag_id "
                    "WHERE at.asset_id = a.id AND lower(t.name) = ?)")
_EXCLUDE_TAG_SQL = ("NOT EXISTS (SELECT 1 FROM asset_tags at JOIN tags t ON t.id = at.tag_id "
                    "WHERE at.asset_id = a.id AND lower(t.name) = ?)")
_COLLECTION_SQL = ("EXISTS (SELECT 1 FROM collection_assets ca "
                   "WHERE ca.asset_id = a.id AND ca.collection_id = ?)")
_FTS_SQL = "EXISTS (SELECT 1 FROM asset_fts WHERE asset_fts.rowid = a.id AND asset_fts MATCH ?)"


def _fts_query(q: str) -> str:
    """Turn user text into a safe FTS5 prefix query."""
    terms = [t for t in "".join(c if c.isalnum() or c.isspace() else " " for c in q).split() if t]
    return " ".join(f'"{t}"*' for t in terms)


def normalize_tags(values: Optional[Iterable[str]]) -> list[str]:
    """Strip, lower-case and de-duplicate tag filters.

    Query strings may arrive either as repeated parameters (``tag=a&tag=b``)
    or as one comma-separated value (``tag=a,b``); both are accepted. Empty
    entries are dropped, so a trailing comma does not create a phantom filter.
    """
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        for part in re.split(r"[,，]", str(value)):
            name = part.strip().lower()
            if name and name not in out:
                out.append(name)
    return out


def build_where(
    *,
    q: str = "",
    media_type: Optional[str] = None,
    tag: Optional[str] = None,
    include_tags: Optional[Iterable[str]] = None,
    exclude_tags: Optional[Iterable[str]] = None,
    collection_id: Optional[int] = None,
    status: str = "active",
) -> tuple[str, list]:
    """Return the common WHERE clause (without WHERE) and bound parameters.

    All conditions are ANDed. EXISTS subqueries avoid the row multiplication
    and DISTINCT that plain joins would introduce with multiple tags.
    """
    clauses = ["a.status = ?"]
    params: list = [status]

    keyword = (q or "").strip()
    if keyword:
        # Punctuation-only input sanitises to no terms. Treat it like blank
        # input instead of issuing an empty MATCH, which FTS5 rejects.
        fts = _fts_query(keyword)
        if fts:
            clauses.append(_FTS_SQL)
            params.append(fts)
    if media_type:
        clauses.append("a.media_type = ?")
        params.append(media_type)
    include_names: list[str] = []
    for name in normalize_tags([tag]) + normalize_tags(include_tags):
        if name not in include_names:  # legacy tag may repeat an include_tag
            include_names.append(name)
            clauses.append(_INCLUDE_TAG_SQL)
            params.append(name)
    for name in normalize_tags(exclude_tags):
        clauses.append(_EXCLUDE_TAG_SQL)
        params.append(name)
    if collection_id is not None:
        clauses.append(_COLLECTION_SQL)
        params.append(collection_id)

    return " AND ".join(clauses), params


def order_by(sort: str) -> str:
    """Resolve a client sort name to a deterministic SQL ORDER BY."""
    return SORTS.get(sort, SORTS[DEFAULT_SORT])


def fetch_rows(filters: dict, limit: Optional[int] = None, offset: int = 0) -> tuple[list[dict], int]:
    """Fetch matching asset rows and the full match count.

    ``limit=None`` means no LIMIT (used by CSV export). Every query reads the
    same filters, so list and export agree as long as the data does not change.
    """
    conn = get_conn()
    where_sql, params = build_where(**{k: v for k, v in filters.items() if k != "sort"})
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM assets a WHERE {where_sql}", params
    ).fetchone()["c"]
    sql = f"SELECT a.* FROM assets a WHERE {where_sql} ORDER BY {order_by(filters.get('sort', DEFAULT_SORT))}"
    query_params = list(params)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        query_params.extend([limit, offset])
    return [dict(r) for r in conn.execute(sql, query_params).fetchall()], total


def search(
    *,
    q: str = "",
    media_type: Optional[str] = None,
    tag: Optional[str] = None,
    include_tags: Optional[Iterable[str]] = None,
    exclude_tags: Optional[Iterable[str]] = None,
    collection_id: Optional[int] = None,
    status: str = "active",
    sort: str = DEFAULT_SORT,
    mode: str = "keyword",
    limit: int = 60,
    offset: int = 0,
) -> dict:
    conn = get_conn()

    # Semantic mode ranks the candidate pool by embedding similarity. It is a
    # legacy mode and deliberately ignores the extra combined filters; the
    # search page only exposes keyword mode.
    if mode == "semantic" and q.strip():
        return _semantic_search(q, media_type, status, limit, offset)

    filters = dict(q=q, media_type=media_type, tag=tag, include_tags=include_tags,
                   exclude_tags=exclude_tags, collection_id=collection_id,
                   status=status, sort=sort)
    rows, total = fetch_rows(filters, limit=limit, offset=offset)
    return {
        "total": total,
        "items": [_card(r) for r in rows],
        "facets": _facets(status),
        "mode": mode,
        "limit": limit,
        "offset": offset,
    }


def _semantic_search(q, media_type, status, limit, offset) -> dict:
    conn = get_conn()
    qvec = ai.embed(q)
    where = ["status = ?", "embedding IS NOT NULL"]
    params: list = [status]
    if media_type:
        where.append("media_type = ?")
        params.append(media_type)
    rows = conn.execute(
        f"SELECT * FROM assets WHERE {' AND '.join(where)}", params
    ).fetchall()
    scored = []
    for r in rows:
        score = ai.cosine(qvec, ai.unpack_embedding(r["embedding"]))
        scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    page = scored[offset:offset + limit]
    items = []
    for score, r in page:
        card = _card(dict(r))
        card["score"] = round(score, 4)
        items.append(card)
    return {"total": len(scored), "items": items, "facets": _facets(status), "mode": "semantic"}


def more_like(asset_id: int, limit: int = 12) -> list[dict]:
    conn = get_conn()
    base = conn.execute("SELECT embedding FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not base or not base["embedding"]:
        return []
    bvec = ai.unpack_embedding(base["embedding"])
    rows = conn.execute(
        "SELECT * FROM assets WHERE id != ? AND status = 'active' AND embedding IS NOT NULL",
        (asset_id,),
    ).fetchall()
    scored = [(ai.cosine(bvec, ai.unpack_embedding(r["embedding"])), r) for r in rows]
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    out = []
    for score, r in scored[:limit]:
        card = _card(dict(r))
        card["score"] = round(score, 4)
        out.append(card)
    return out


def _facets(status: str) -> dict:
    conn = get_conn()
    media = conn.execute(
        "SELECT media_type, COUNT(*) c FROM assets WHERE status = ? GROUP BY media_type ORDER BY c DESC",
        (status,),
    ).fetchall()
    tags = conn.execute(
        """SELECT t.name, COUNT(*) c FROM tags t
           JOIN asset_tags at ON at.tag_id = t.id
           JOIN assets a ON a.id = at.asset_id AND a.status = ?
           GROUP BY t.name ORDER BY c DESC LIMIT 25""",
        (status,),
    ).fetchall()
    return {
        "media_types": [{"value": r["media_type"], "count": r["c"]} for r in media],
        "tags": [{"value": r["name"], "count": r["c"]} for r in tags],
    }


def _card(a: dict) -> dict:
    """Compact asset representation for grid/list views."""
    return {
        "id": a["id"],
        "uuid": a["uuid"],
        "title": a["title"],
        "filename": a["filename"],
        "media_type": a["media_type"],
        "mime_type": a["mime_type"],
        "ext": a["ext"],
        "size": a["size"],
        "width": a["width"],
        "height": a["height"],
        "alt_text": a["alt_text"],
        "status": a["status"],
        "created_at": a["created_at"],
    }
