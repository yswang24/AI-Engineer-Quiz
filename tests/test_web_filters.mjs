import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { splitTags, queryParams } = require("../web/filters.js");

test("splitTags normalises, splits and de-duplicates", () => {
  assert.deepEqual(splitTags(" Approved, campaign，APPROVED , , internal "),
                   ["approved", "campaign", "internal"]);
  assert.deepEqual(splitTags("   "), []);
  assert.deepEqual(splitTags(null), []);
});

test("queryParams carries every combined filter as repeated params", () => {
  const p = queryParams({
    q: "  harbor  ", media: "image", collection: 7,
    includeTags: ["approved", "campaign"], excludeTags: ["internal"],
    sort: "oldest", limit: 3, offset: 6,
  });
  assert.equal(p.get("q"), "harbor");
  assert.equal(p.get("media_type"), "image");
  assert.equal(p.get("collection_id"), "7");
  assert.deepEqual(p.getAll("include_tags"), ["approved", "campaign"]);
  assert.deepEqual(p.getAll("exclude_tags"), ["internal"]);
  assert.equal(p.get("sort"), "oldest");
  assert.equal(p.get("limit"), "3");
  assert.equal(p.get("offset"), "6");
});

test("queryParams omits blank keyword and pagination for export", () => {
  const p = queryParams({ q: "   ", includeTags: [], excludeTags: [], sort: "newest" }, false);
  assert.equal(p.has("q"), false);
  assert.equal(p.has("limit"), false);
  assert.equal(p.has("offset"), false);
  assert.equal(p.get("sort"), "newest");
});
