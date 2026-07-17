import assert from "node:assert/strict";
import test from "node:test";

import {
  presentTaskRecommendations,
  recommendationChanges,
  recommendationSnapshots,
} from "../src/lib/tasks-projection-presentation.ts";


function task(id, content) {
  return { id, content, section: "Personal", completed: false, labels: [] };
}


function area(recommendation, state = recommendation ? "recommended" : "empty") {
  return {
    area: "Personal",
    section_name: "Personal",
    task_count: recommendation ? 2 : 0,
    state,
    recommendation,
  };
}


function recommendation(id, title, explanation = "Backend evidence explains this choice.") {
  return {
    provider: "todoist",
    provider_record_id: id,
    title,
    task: task(id, title),
    action: "do_work",
    score: 40,
    explanation,
    evidence: [],
    alternatives: [{
      provider: "todoist",
      provider_record_id: "alternative",
      title: "Alternative",
      task: task("alternative", "Alternative"),
      score: 10,
      action: "do_work",
    }],
    computed_at: "2026-07-17T12:00:00-04:00",
    context: {},
  };
}


test("Tasks presentation renders backend choice, explanation, and alternative order", () => {
  const [presented] = presentTaskRecommendations([area(recommendation("selected", "Selected"))]);

  assert.equal(presented.task.id, "selected");
  assert.equal(presented.reason, "Backend evidence explains this choice.");
  assert.deepEqual(presented.tasks.map((item) => item.id), ["selected", "alternative"]);
});


test("Tasks presentation distinguishes connected empty and provider unavailable", () => {
  assert.equal(presentTaskRecommendations([area(null)])[0].reason, "No active Personal tasks");
  assert.equal(
    presentTaskRecommendations([area(null, "unavailable")])[0].reason,
    "Todoist recommendations unavailable",
  );
});


test("refresh comparison stores identity only and uses the new backend explanation", () => {
  const previous = recommendationSnapshots([area(recommendation("old", "Old"))]);
  const next = area(recommendation("new", "New", "Due today."));

  assert.deepEqual(previous, [{
    area: "Personal",
    provider: "todoist",
    providerRecordId: "old",
    taskContent: "Old",
  }]);
  assert.deepEqual(recommendationChanges(previous, [next]), [{
    area: "Personal",
    previous: "Old",
    current: "New",
    reason: "Due today.",
  }]);
});
