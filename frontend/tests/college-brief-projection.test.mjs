import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


test("Today renders the backend College projection without client ranking", async () => {
  const source = await readFile("src/app/today/page.tsx", "utf8");

  assert.match(source, /college_attention_projection/);
  assert.match(source, /college\.opening/);
  assert.match(source, /college\.decisive_items\.slice\(1\)/);
  assert.match(source, /college\.coverage_gaps\.map/);
  assert.doesNotMatch(source, /college\.decisive_items\.sort/);
  assert.doesNotMatch(source, /score\s*[+\-]=/);
});


test("Morning exposes shared College evidence and honest Blinn pending language", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");

  assert.match(source, /synthesis\.college\.coverage_gaps/);
  assert.match(source, /synthesis\.college\.evidence_refs/);
  assert.match(source, /Blinn remains pending/);
  assert.match(source, /does not imply that its mailbox was checked/);
});
