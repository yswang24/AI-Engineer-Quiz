/* Pure helpers for the combined-filter page: no DOM, no network, easy to test. */
(function (root) {
  "use strict";

  function splitTags(raw) {
    return (raw || "")
      .split(/[,，]/)
      .map(s => String(s).trim().toLowerCase())
      .filter(Boolean)
      .filter((v, i, a) => a.indexOf(v) === i);
  }

  function queryParams(state, withPage = true) {
    const p = new URLSearchParams();
    if (String(state.q || "").trim()) p.set("q", String(state.q).trim());
    if (state.media) p.set("media_type", state.media);
    if (state.collection) p.set("collection_id", String(state.collection));
    (state.includeTags || []).forEach(t => p.append("include_tags", t));
    (state.excludeTags || []).forEach(t => p.append("exclude_tags", t));
    p.set("sort", state.sort || "newest");
    if (withPage) {
      p.set("limit", String(state.limit || 12));
      p.set("offset", String(state.offset || 0));
    }
    return p;
  }

  const SORTS = ["newest", "oldest", "name", "largest"];

  function fromLocationSearch(search) {
    const p = new URLSearchParams(search || "");
    const limit = Number(p.get("limit"));
    const offset = Number(p.get("offset"));
    const sort = p.get("sort");
    return {
      q: p.get("q") || "",
      media: p.get("media_type") || null,
      collection: p.get("collection_id") || null,
      includeTags: splitTags(p.getAll("include_tags").join(",")),
      excludeTags: splitTags(p.getAll("exclude_tags").join(",")),
      sort: SORTS.includes(sort) ? sort : "newest",
      limit: Number.isFinite(limit) && limit >= 1 && limit <= 200 ? limit : 12,
      offset: Number.isFinite(offset) && offset >= 0 ? offset : 0,
    };
  }

  const api = { splitTags, queryParams, fromLocationSearch };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KeepstackFilters = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
