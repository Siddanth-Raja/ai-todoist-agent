import assert from "node:assert/strict";
import test from "node:test";

import {
  todayMustDoItemLabel,
  todayMustDoPresentation,
  todayProjectCardPresentation,
  todayRecommendationBadge,
} from "../src/lib/today-projection-presentation.ts";


const area = {
  name: "XO",
  description: "VR project",
  project_key: "xo",
  canonical_project_id: "xo-id",
  status: "Needs attention",
  next_recommendation: "Work next: Review controller notes",
  task_count: 2,
  overdue_count: 0,
  today_count: 0,
  high_priority_count: 1,
  provider_status: "connected",
  provider_message: "Mapped Linear work loaded successfully.",
  degraded: false,
};

test("Today project cards present canonical Project Brain status and next move", () => {
  assert.deepEqual(todayProjectCardPresentation(area), {
    status: "Needs attention",
    nextMove: "Work next: Review controller notes",
    failure: null,
  });
});

test("Today project cards preserve provider failure instead of showing false empty state", () => {
  assert.deepEqual(
    todayProjectCardPresentation({
      ...area,
      provider_status: "provider_failure",
      provider_message: "Linear could not be reached.",
      degraded: true,
    }),
    {
      status: "Needs attention",
      nextMove: "Work next: Review controller notes",
      failure: "Linear could not be reached.",
    },
  );
});

test("Today recommendation badges distinguish shared output, contextual override, and Calendar-first prep", () => {
  assert.equal(
    todayRecommendationBadge({ source: "shared_recommendation", contextual_override: false }),
    "Shared recommendation",
  );
  assert.equal(
    todayRecommendationBadge({ source: "shared_recommendation", contextual_override: true }),
    "Contextual shared override",
  );
  assert.equal(
    todayRecommendationBadge({ source: "calendar", contextual_override: false }),
    "Calendar-first",
  );
});

test("Today Must do distinguishes connected empty from unavailable provider state", () => {
  assert.deepEqual(
    todayMustDoPresentation({ state: "available", items: [], errors: [], providers: [] }),
    {
      emptyTitle: "No overdue or due-today obligations",
      warning: null,
    },
  );
  assert.deepEqual(
    todayMustDoPresentation({
      state: "unavailable",
      items: [],
      errors: ["Could not read Todoist tasks."],
      providers: [{
        provider: "todoist",
        provider_reference: null,
        available: false,
        error: "Could not read Todoist tasks.",
      }],
    }),
    {
      emptyTitle: "Must do data unavailable",
      warning: "Could not read Todoist tasks.",
    },
  );
});

test("Today Must do labels overdue and due-today obligations distinctly", () => {
  assert.equal(todayMustDoItemLabel({ urgency: "overdue", days_overdue: 3 }), "3 days overdue");
  assert.equal(todayMustDoItemLabel({ urgency: "overdue", days_overdue: 1 }), "1 day overdue");
  assert.equal(todayMustDoItemLabel({ urgency: "due_today", days_overdue: 0 }), "Due today");
});
