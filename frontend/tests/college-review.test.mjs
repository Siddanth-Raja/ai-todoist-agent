import assert from "node:assert/strict";
import test from "node:test";
import {
  collectCollegePages,
  collegeRecordGroups,
  readableCollegeValue,
  sourceLabel,
  knownPrecommitRejection,
  collegeClaimDisplay,
  collegeConflictDisplay,
  capturePreferenceCopy,
  invalidateDependentCollegeDetails,
  createCollegeReadGate,
} from "../src/lib/college-review.ts";

test("bounded College paging follows one query and preserves server order", async () => {
  const visited = [];
  const pages = [
    { records: [{ record_type: "identity", record_id: "a" }], pagination: { next_cursor: "a/b+" } },
    { records: [{ record_type: "claim", record_id: "b" }], pagination: { next_cursor: "next" } },
    { records: [{ record_type: "coverage", record_id: "c" }], pagination: { next_cursor: null } },
  ];
  const result = await collectCollegePages("scope=cross_course&horizon_start=stable", async (path) => {
    visited.push(path);
    return pages[visited.length - 1];
  });
  assert.deepEqual(result.records.map((item) => item.record_id), ["a", "b", "c"]);
  assert.equal(visited.length, 3);
  assert.match(visited[1], /horizon_start=stable&cursor=a%2Fb%2B$/);
  assert.equal(result.pagination.next_cursor, null);
});

test("unknown capture preference is never displayed as revoked", () => {
  assert.match(capturePreferenceCopy(null), /unavailable/);
  assert.equal(capturePreferenceCopy({ active: false }), "Off. Reports are not sent until you opt in.");
});

test("deadline precision and recorded conflict reason remain visible", () => {
  assert.deepEqual(collegeClaimDisplay("deadline", {
    value: "2026-10-01", precision: "date", timezone: "America/Chicago", kind: "official",
  }), { title: "Deadline", detail: "2026-10-01 · America/Chicago · official", qualification: "Date only; no time of day is established." });
  assert.equal(collegeClaimDisplay("deadline", {
    value: { lower: null, upper: null }, precision: "unknown",
  }).qualification, "The timing needs review before relying on it.");
  assert.deepEqual(collegeConflictDisplay("deadline", "authority_conflict"), {
    field: "deadline", reason: "authority conflict",
  });
});

test("older reads cannot restore state after a mutation or newer refresh", () => {
  const gate = createCollegeReadGate();
  const beforeMutation = gate.begin();
  gate.invalidate();
  assert.equal(gate.isCurrent(beforeMutation), false);
  const afterMutation = gate.begin();
  assert.equal(gate.isCurrent(afterMutation), true);
  const newer = gate.begin();
  assert.equal(gate.isCurrent(afterMutation), false);
  assert.equal(gate.isCurrent(newer), true);
});

test("after a lifecycle change cached claims and assessments are withheld until reread", () => {
  const previous = { status: "ready", records: [
    { record_type: "identity", record_id: "course" },
    { record_type: "claim", record_id: "forgotten" },
    { record_type: "conflict", record_id: "dependent" },
    { record_type: "coverage", record_id: "source" },
    { record_type: "assessment", record_id: "old-judgment" },
  ] };
  const next = invalidateDependentCollegeDetails(previous);
  assert.deepEqual(next.records.map((record) => record.record_type), ["identity", "coverage"]);
  assert.equal(next.assessment_status, "needs_refresh");
  assert.equal(previous.records.length, 5);
});

test("session observations show their reported meaning instead of internal identifiers", () => {
  assert.deepEqual(collegeClaimDisplay("session:opaque:topic:topic_covered", {
    kind: "topic_covered", value: "continuity", asserted_at: "synthetic",
  }), { title: "Topic covered", detail: "continuity", qualification: "Reported class coverage does not establish understanding." });
  assert.deepEqual(collegeClaimDisplay("session:opaque:check:assessment_observed", {
    kind: "assessment_observed", value: { kind: "quick_check", status: "occurred", outcome: "unknown" },
  }), { title: "Quick check", detail: "Occurred in class", qualification: "Result was not reported." });
  assert.equal(collegeClaimDisplay("session:opaque:announcement:announcement_reported", {
    kind: "announcement_reported", value: "exam warning",
  }).detail, "exam warning");
});

test("known precommit rejections release retry lock while server failures stay uncertain", () => {
  assert.equal(knownPrecommitRejection(400), true);
  assert.equal(knownPrecommitRejection(403), true);
  assert.equal(knownPrecommitRejection(409), true);
  assert.equal(knownPrecommitRejection(503), false);
  assert.equal(knownPrecommitRejection(408), false);
  assert.equal(knownPrecommitRejection(429), false);
});

test("College paging stays bounded even when the server has more", async () => {
  let calls = 0;
  const result = await collectCollegePages("scope=cross_course", async () => {
    calls += 1;
    return { records: [{ record_type: "claim", record_id: String(calls) }], pagination: { next_cursor: "another" } };
  }, 4);
  assert.equal(calls, 4);
  assert.equal(result.records.length, 4);
  assert.equal(result.pagination.next_cursor, "another");
});

test("review grouping retains distinct claim, conflict, coverage and assessment records", () => {
  const groups = collegeRecordGroups([
    { record_type: "identity", record_id: "1" },
    { record_type: "claim", record_id: "2" },
    { record_type: "conflict", record_id: "3" },
    { record_type: "coverage", record_id: "4" },
    { record_type: "assessment", record_id: "5" },
  ]);
  assert.deepEqual(Object.values(groups).map((items) => items.length), [1, 1, 1, 1, 1]);
  assert.equal(sourceLabel("user_confirmed"), "Your report");
  assert.equal(readableCollegeValue({ deadline: "Friday", schema_version: "internal" }), "deadline: Friday");
});

test("delivery journal survives reload with exact payload and isolated connection, then clears", async () => {
  const { collegeDeliveryKey, readCollegeDelivery, writeCollegeDelivery } = await import('../src/lib/college-review.ts');
  const entries = new Map();
  const storage = { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
  const key = await collegeDeliveryKey('http://localhost:8003', 'secret-key');
  const command = { path: '/college/update', label: 'College report', payload: { command_id: 'original', idempotency_key: 'original-key', message: 'synthetic report', asserted_at: 'original-time' } };
  const saved = writeCollegeDelivery(storage, key, command);
  assert.deepEqual(readCollegeDelivery(storage, await collegeDeliveryKey('http://localhost:8003', 'secret-key')), saved);
  assert.equal(readCollegeDelivery(storage, await collegeDeliveryKey('http://localhost:8003', 'different-key')), null);
  assert.equal(readCollegeDelivery(storage, await collegeDeliveryKey('http://other:8003', 'secret-key')), null);
  assert.ok(!JSON.stringify([...entries]).includes('secret-key'));
  const expired = readCollegeDelivery(storage, key, saved.expiresAt);
  assert.equal(expired.retryExpired, true);
  assert.deepEqual(expired.payload, { command_id: 'original', idempotency_key: 'original-key' });
  assert.ok(!entries.get(key).includes('synthetic report'));
  writeCollegeDelivery(storage, key, null);
  assert.equal(readCollegeDelivery(storage, key), null);
});

test("unavailable or corrupt delivery storage fails closed", async () => {
  const { readCollegeDelivery, writeCollegeDelivery } = await import('../src/lib/college-review.ts');
  assert.throws(() => readCollegeDelivery({ getItem: () => '{broken' }, 'key'));
  assert.throws(() => readCollegeDelivery({ getItem: () => '{}' }, 'key'), /cannot be recovered/);
  assert.throws(() => writeCollegeDelivery({ setItem: () => { throw new Error('quota'); } }, 'key', {payload:{}}), /quota/);
});
