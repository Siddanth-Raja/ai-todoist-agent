import assert from "node:assert/strict";
import test from "node:test";

import {
  CHAT_SESSION_KEY,
  getOrCreateChatSessionId,
  pendingActionReference,
} from "../src/lib/pending-action.ts";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
  };
}

test("chat session identity survives refresh", () => {
  const storage = memoryStorage();
  const first = getOrCreateChatSessionId(storage, () => "session-first");
  const second = getOrCreateChatSessionId(storage, () => "session-second");

  assert.equal(first, "session-first");
  assert.equal(second, "session-first");
  assert.equal(storage.getItem(CHAT_SESSION_KEY), "session-first");
});

test("confirmation request is derived only from the durable action reference", () => {
  const fingerprint = "a".repeat(64);
  assert.deepEqual(
    pendingActionReference({
      action_id: "action-123",
      version: 4,
      fingerprint,
      task: { content: "display-only preview" },
    }),
    {
      action_id: "action-123",
      expected_version: 4,
      fingerprint,
    },
  );
});

test("missing, malformed, and legacy dictionary-only references are rejected", () => {
  for (const value of [
    null,
    {},
    { type: "create_todoist_task", task: { content: "legacy" } },
    { action_id: "action", version: 0, fingerprint: "a".repeat(64) },
    { action_id: "action", version: 1, fingerprint: "short" },
  ]) {
    assert.equal(pendingActionReference(value), null);
  }
});
