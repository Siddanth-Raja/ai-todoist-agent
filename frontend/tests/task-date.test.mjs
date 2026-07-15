import assert from "node:assert/strict";
import test from "node:test";

import {
  formatTaskDate,
  parseTaskDate,
  taskDateTime,
  taskDueDateValue,
} from "../src/lib/task-date.ts";

test("valid created_at and due values parse safely", () => {
  assert.equal(
    parseTaskDate("2026-07-14T10:30:00Z")?.toISOString(),
    "2026-07-14T10:30:00.000Z",
  );
  assert.ok(Number.isFinite(taskDateTime("2026-07-14")));
  assert.equal(taskDateTime("1970-01-01T00:00:00Z"), 0);
  assert.notEqual(
    formatTaskDate("2026-07-14", { month: "short", day: "numeric" }, "Absent"),
    "Absent",
  );
});

test("task due values safely handle valid, null, missing, and malformed input", () => {
  assert.equal(taskDueDateValue({ due_date: "2026-07-14" }), "2026-07-14");
  assert.equal(taskDueDateValue({ due_date: null, due: { date: "2026-07-15" } }), "2026-07-15");
  assert.equal(taskDueDateValue({ due_date: "bad", due: { date: "2026-07-16" } }), "2026-07-16");
  assert.equal(taskDueDateValue({ due_date: null, due: null }), null);
  assert.equal(taskDueDateValue({}), null);
  assert.equal(taskDueDateValue({ due_date: "not-a-date", due: { date: "2026-02-30" } }), null);
});

test("null, missing, and empty task dates are absent", () => {
  for (const value of [null, undefined, "", "   "]) {
    assert.equal(parseTaskDate(value), null);
    assert.equal(taskDateTime(value), null);
    assert.equal(
      formatTaskDate(value, { month: "short", day: "numeric" }, "No due date"),
      "No due date",
    );
  }
});

test("malformed and impossible task dates are absent", () => {
  for (const value of ["not-a-date", "2026-02-30", "2026-13-01", "2026-07-14T99:00:00Z"]) {
    assert.equal(parseTaskDate(value), null);
    assert.equal(taskDateTime(value), null);
    assert.equal(
      formatTaskDate(value, { month: "short", day: "numeric" }, "No due date"),
      "No due date",
    );
  }
});
