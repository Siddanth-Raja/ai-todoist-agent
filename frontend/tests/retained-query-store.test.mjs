import assert from "node:assert/strict";
import test from "node:test";

import { RetainedQueryStore } from "../src/lib/retained-query-store.ts";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolveValue, rejectValue) => {
    resolve = resolveValue;
    reject = rejectValue;
  });
  return { promise, resolve, reject };
}

test("cold success becomes retained state and background success replaces it", async () => {
  const store = new RetainedQueryStore();
  const scope = {};

  assert.equal(store.snapshot(scope, "/today").isInitialLoading, true);
  await store.refresh(scope, "/today", async () => ({ version: 1 }));
  assert.deepEqual(store.snapshot(scope, "/today").data, { version: 1 });

  const next = deferred();
  const refresh = store.refresh(scope, "/today", () => next.promise);
  assert.equal(store.snapshot(scope, "/today").isRefreshing, true);
  assert.deepEqual(store.snapshot(scope, "/today").data, { version: 1 });
  next.resolve({ version: 2 });
  await refresh;
  assert.deepEqual(store.snapshot(scope, "/today").data, { version: 2 });
});

test("initial failure is real while refresh failure retains successful state and later recovers", async () => {
  const store = new RetainedQueryStore();
  const scope = {};

  await assert.rejects(
    store.refresh(scope, "/today", async () => {
      throw new Error("provider unavailable");
    }),
  );
  assert.equal(store.snapshot(scope, "/today").data, null);
  assert.equal(store.snapshot(scope, "/today").initialError, "provider unavailable");

  await store.refresh(scope, "/today", async () => ({ version: 1 }));
  await assert.rejects(
    store.refresh(scope, "/today", async () => {
      throw new Error("refresh failed");
    }),
  );
  assert.deepEqual(store.snapshot(scope, "/today").data, { version: 1 });
  assert.equal(store.snapshot(scope, "/today").refreshError, "refresh failed");

  await store.refresh(scope, "/today", async () => ({ version: 2 }));
  assert.equal(store.snapshot(scope, "/today").refreshError, null);
  assert.deepEqual(store.snapshot(scope, "/today").data, { version: 2 });
});

test("equivalent in-flight requests deduplicate", async () => {
  const store = new RetainedQueryStore();
  const scope = {};
  const request = deferred();
  let calls = 0;
  const load = () => {
    calls += 1;
    return request.promise;
  };

  const first = store.refresh(scope, "/tasks", load);
  const second = store.refresh(scope, "/tasks", load);
  assert.equal(calls, 1);
  assert.equal(first, second);
  request.resolve({ ok: true });
  await first;
});

test("an older response cannot overwrite a newer forced refresh", async () => {
  const store = new RetainedQueryStore();
  const scope = {};
  const oldRequest = deferred();
  const newRequest = deferred();

  const oldRefresh = store.refresh(scope, "/calendar", () => oldRequest.promise);
  const newRefresh = store.refresh(scope, "/calendar", () => newRequest.promise, {
    force: true,
  });
  newRequest.resolve({ version: 2 });
  await newRefresh;
  oldRequest.resolve({ version: 1 });
  await oldRefresh;

  assert.deepEqual(store.snapshot(scope, "/calendar").data, { version: 2 });
});

test("connection and request keys isolate retained state", async () => {
  const store = new RetainedQueryStore();
  const connectionA = {};
  const connectionB = {};

  await store.refresh(connectionA, "/projects", async () => ["A"]);
  await store.refresh(connectionA, "/projects?archived=true", async () => ["archived"]);

  assert.deepEqual(store.snapshot(connectionA, "/projects").data, ["A"]);
  assert.deepEqual(store.snapshot(connectionA, "/projects?archived=true").data, ["archived"]);
  assert.equal(store.snapshot(connectionB, "/projects").data, null);
});
