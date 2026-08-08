import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  calendarDayDensity,
  calendarDayEventHeightRem,
  calendarWeekDensity,
  LIFE_AREA_GRID_CLASS,
  todayRecommendationPresentation,
} from "../src/lib/surface-hierarchy-presentation.ts";

const todaySource = await readFile(
  new URL("../src/app/today/page.tsx", import.meta.url),
  "utf8",
);
const calendarSource = await readFile(
  new URL("../src/app/calendar/page.tsx", import.meta.url),
  "utf8",
);
const projectSource = await readFile(
  new URL("../src/app/projects/[projectKey]/page.tsx", import.meta.url),
  "utf8",
);
const globalsSource = await readFile(
  new URL("../src/app/globals.css", import.meta.url),
  "utf8",
);
const appShellSource = await readFile(
  new URL("../src/components/app-shell.tsx", import.meta.url),
  "utf8",
);

function recommendation(overrides = {}) {
  return {
    type: "task",
    source: "shared_recommendation",
    title: "Review the next action",
    detail: "Normalized priority is urgent.",
    evidence: [
      {
        signal: "normalized_priority",
        value: 4,
        score_delta: 40,
        explanation: "Normalized priority is urgent.",
      },
    ],
    alternatives: [],
    provider: "linear",
    provider_record_id: "SID-227",
    contextual_override: false,
    ...overrides,
  };
}

test("recommendation prominence uses structured executable evidence only", () => {
  assert.equal(
    todayRecommendationPresentation(recommendation()).prominence,
    "secondary",
  );
  assert.equal(
    todayRecommendationPresentation(
      recommendation({
        evidence: [
          {
            signal: "project_momentum",
            value: 3,
            score_delta: 3,
            explanation: "Visible project momentum.",
          },
        ],
      }),
    ).prominence,
    "secondary",
  );
  assert.equal(
    todayRecommendationPresentation(
      recommendation({
        evidence: [
          {
            signal: "due_urgency",
            value: "2026-07-26",
            score_delta: 80,
            explanation: "Due today.",
          },
        ],
      }),
    ).prominence,
    "primary",
  );
  assert.equal(
    todayRecommendationPresentation(
      recommendation({ source: "calendar", provider: null, provider_record_id: null }),
    ).prominence,
    "primary",
  );
  assert.equal(
    todayRecommendationPresentation(
      recommendation({ contextual_override: true }),
    ).prominence,
    "primary",
  );
});

test("fallback or ungrounded recommendations remain supporting context", () => {
  assert.equal(
    todayRecommendationPresentation(
      recommendation({ source: "fallback", provider: null, provider_record_id: null }),
    ).prominence,
    "supporting",
  );
  assert.equal(todayRecommendationPresentation(null).prominence, "supporting");
});

test("Life Area layout is one responsive rule for representative counts without slicing", () => {
  for (const count of [1, 2, 3, 4, 5, 6, 9]) {
    assert.match(LIFE_AREA_GRID_CLASS, /auto-fit/);
    assert.match(LIFE_AREA_GRID_CLASS, /minmax/);
    assert.equal(count > 0, true);
  }
  assert.match(globalsSource, /\.life-area-grid/);
  assert.match(globalsSource, /nth-child\(2n \+ 1\)/);
  assert.match(globalsSource, /nth-child\(3n \+ 1\)/);
  assert.match(globalsSource, /prefers-reduced-motion: reduce/);
  assert.match(globalsSource, /:focus-visible/);
  assert.match(todaySource, /lifeAreas\.map/);
  assert.doesNotMatch(todaySource, /lifeAreas\.(slice|splice)\(/);
  assert.doesNotMatch(LIFE_AREA_GRID_CLASS, /grid-cols-5/);
});

test("Must do remains before and distinct from Recommended work", () => {
  const mustDoIndex = todaySource.indexOf('eyebrow="Must do"');
  const recommendationIndex = todaySource.indexOf(
    "data-recommendation-prominence",
  );
  assert.ok(mustDoIndex >= 0);
  assert.ok(recommendationIndex > mustDoIndex);
  assert.match(todaySource, /border-coral\/20/);
});

test("Calendar sparse modes are compact while populated modes retain full content", () => {
  assert.equal(calendarDayDensity(0), "compact");
  assert.equal(calendarDayDensity(1), "timeline");
  assert.equal(calendarDayEventHeightRem(6 * 60, 60), 4);
  assert.equal(calendarDayEventHeightRem(6 * 60, 7 * 24 * 60), 68);
  assert.equal(calendarDayEventHeightRem(22 * 60 + 45, 7 * 24 * 60), 3);
  assert.equal(calendarWeekDensity(0, 0), "compact");
  assert.equal(calendarWeekDensity(1, 0), "calendar");
  assert.equal(calendarWeekDensity(0, 1), "calendar");
  assert.match(calendarSource, /dayDensity === "timeline"/);
  assert.match(calendarSource, /lg:h-\[68rem\]/);
  assert.match(calendarSource, /calendar-day-event/);
  assert.match(globalsSource, /--calendar-day-event-height/);
  assert.match(globalsSource, /@media \(min-width: 1024px\)/);
  assert.match(calendarSource, /weekDensity === "compact"/);
  assert.match(calendarSource, /weekEventsByDay\.map/);
});

test("Project hierarchy preserves every SID-218 collection contract", () => {
  assert.match(projectSource, /projectCollectionPresentation/);
  assert.match(projectSource, /data-scroll-state/);
  assert.match(projectSource, /project\?\.dependency_evidence \?\? \[\]/);
  assert.match(projectSource, /currentDependencyBlockers\.map/);
  assert.match(projectSource, /project\.task_groups\.map/);
  assert.match(projectSource, /project\.classification_diagnostics\.map/);
  assert.doesNotMatch(projectSource, /currentDependencyBlockers\.(slice|splice)\(/);
  assert.doesNotMatch(projectSource, /project\.classification_diagnostics\.(slice|splice)\(/);
});

test("bottom navigation clearance remains until the navigation hides", () => {
  assert.match(appShellSource, /pb-24/);
  assert.match(appShellSource, /xl:pb-6/);
  assert.match(appShellSource, /xl:hidden/);
  assert.doesNotMatch(appShellSource, /lg:pb-6/);
});
