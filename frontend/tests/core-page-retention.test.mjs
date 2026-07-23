import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pages = {
  today: await readFile(new URL("../src/app/today/page.tsx", import.meta.url), "utf8"),
  tasks: await readFile(new URL("../src/app/tasks/page.tsx", import.meta.url), "utf8"),
  projects: await readFile(new URL("../src/app/projects/page.tsx", import.meta.url), "utf8"),
  project: await readFile(new URL("../src/app/projects/[projectKey]/page.tsx", import.meta.url), "utf8"),
  calendar: await readFile(new URL("../src/app/calendar/page.tsx", import.meta.url), "utf8"),
  email: await readFile(new URL("../src/app/email/page.tsx", import.meta.url), "utf8"),
};

test("core read surfaces share the session-retained query boundary", () => {
  for (const [name, source] of Object.entries(pages)) {
    assert.match(source, /useRetainedApiQuery/, `${name} must retain successful reads`);
  }
});

test("Today retains its independently-failing Today and Activity reads", () => {
  assert.match(pages.today, /useRetainedApiQuery<TodayResponse>\("\/today"\)/);
  assert.match(
    pages.today,
    /useRetainedApiQuery<ActivityEntry\[\]>\("\/activity\?limit=5"\)/,
  );
  assert.match(pages.today, /todayQuery\.initialError \?\? todayQuery\.refreshError/);
});

test("manual Tasks, Calendar, and Email refresh controls force a real refresh", () => {
  assert.match(pages.tasks, /query\.refresh\(\)/);
  assert.match(pages.calendar, /query\.refresh\(\)/);
  assert.match(pages.email, /query\.refresh\(\)/);
});

test("retained Project state remains visible when background refresh fails", () => {
  assert.match(pages.today, /Today refresh failed; showing retained state/);
  assert.match(pages.tasks, /Refresh failed; showing retained tasks/);
  assert.match(pages.projects, /Project refresh failed; showing retained state/);
  assert.match(pages.project, /Project refresh failed; showing retained state/);
  assert.match(pages.calendar, /Refresh failed; showing retained calendar/);
  assert.match(pages.email, /Refresh failed; showing retained email state/);
});
