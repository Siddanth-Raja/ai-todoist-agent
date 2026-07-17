import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const tasksPage = await readFile(new URL("../src/app/tasks/page.tsx", import.meta.url), "utf8");


test("Tasks page contains no independent recommendation scorer or policy", () => {
  for (const legacyPolicy of [
    "recommendationScore",
    "rankRecommendedTasks",
    "focusReason",
    "dueUrgencyScore",
    "unblockingScore",
    "projectMomentumScore",
    "compareRecommendationScores",
  ]) {
    assert.equal(tasksPage.includes(legacyPolicy), false, `${legacyPolicy} must be backend-owned`);
  }
});


test("Tasks refresh consumes backend recommendations", () => {
  assert.match(tasksPage, /nextData\.recommendations/);
  assert.doesNotMatch(tasksPage, /score\.priority|score\.age|score\.unblocking|score\.momentum|score\.due/);
});
