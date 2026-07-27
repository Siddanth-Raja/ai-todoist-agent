import assert from "node:assert/strict";
import test from "node:test";

import {
  currentDependencyEvidence,
  dependencyEvidencePresentation,
  packageAvailabilityPresentation,
  projectDependencyMetricLabels,
  workPackageSectionState,
} from "../src/lib/work-package-presentation.ts";
import {
  projectCollectionKeyboardScroll,
  projectCollectionPresentation,
} from "../src/lib/project-panel-presentation.ts";

test("live SID-226 dependency volumes activate responsive bounded scrolling", () => {
  for (const recordCount of [63, 18, 8, 23]) {
    const presentation = projectCollectionPresentation({
      recordCount,
      overflowThreshold: 4,
    });
    assert.equal(presentation.isBounded, true);
    assert.equal(presentation.tabIndex, 0);
    assert.match(presentation.className, /md:max-h/);
    assert.match(presentation.className, /md:overflow-y-auto/);
    assert.doesNotMatch(presentation.className, /(^|\s)max-h/);
    assert.doesNotMatch(presentation.className, /(^|\s)overflow-y-auto/);
  }
});

test("empty and short collections remain compact and naturally sized", () => {
  for (const recordCount of [0, 1, 4]) {
    assert.deepEqual(
      projectCollectionPresentation({ recordCount, overflowThreshold: 4 }),
      { className: "", isBounded: false, tabIndex: undefined },
    );
  }
});

test("diagnostic collections use the taller responsive bound", () => {
  const presentation = projectCollectionPresentation({
    recordCount: 40,
    overflowThreshold: 6,
    density: "diagnostics",
  });
  assert.equal(presentation.isBounded, true);
  assert.match(presentation.className, /42rem/);
  assert.match(presentation.className, /scrollbar-gutter:stable/);
  assert.match(presentation.className, /focus-visible:ring-2/);
});

test("bounded collections expose deterministic keyboard scrolling without hiding records", () => {
  const dimensions = {
    clientHeight: 544,
    scrollHeight: 11029,
  };
  assert.equal(
    projectCollectionKeyboardScroll({
      key: "PageDown",
      current: 0,
      ...dimensions,
    }),
    462,
  );
  assert.equal(
    projectCollectionKeyboardScroll({
      key: "End",
      current: 462,
      ...dimensions,
    }),
    10485,
  );
  assert.equal(
    projectCollectionKeyboardScroll({
      key: "Home",
      current: 10485,
      ...dimensions,
    }),
    0,
  );
  assert.equal(
    projectCollectionKeyboardScroll({
      key: "Tab",
      current: 0,
      ...dimensions,
    }),
    null,
  );
});

test("project dependency metrics use full evaluated counts and separate review state", () => {
  assert.deepEqual(
    projectDependencyMetricLabels({
      active_dependency_count: 63,
      active_blocked_work_count: 33,
      needs_review_dependency_count: 1,
      needs_review_blocked_work_count: 1,
      resolved_dependency_count: 35,
    }),
    ["63 active dependencies", "1 needs review"],
  );
});

const mappedDiagnostic = {
  provider: "linear",
  status: "connected",
  provider_ref: "project-uuid",
  issue_count: 2,
  message: "Mapped Linear work loaded successfully.",
};

test("available packages present an executable choice", () => {
  assert.deepEqual(packageAvailabilityPresentation("available"), {
    label: "Available",
    detail: "An executable next action is ready.",
    tone: "available",
  });
  assert.equal(workPackageSectionState([{}], mappedDiagnostic), "options");
});

test("explicitly blocked packages present a blocker state", () => {
  const presentation = packageAvailabilityPresentation("explicitly_blocked");
  assert.equal(presentation.label, "Explicitly blocked");
  assert.match(presentation.detail, /explicitly blocked/i);
  assert.equal(presentation.tone, "warning");
});

test("needs-review packages preserve uncertainty", () => {
  const presentation = packageAvailabilityPresentation("needs_review");
  assert.equal(presentation.label, "Needs review");
  assert.match(presentation.detail, /reviewed/i);
  assert.equal(presentation.tone, "warning");
});

test("dependency evidence distinguishes active and needs-review while hiding resolved", () => {
  assert.deepEqual(dependencyEvidencePresentation("active"), {
    label: "Active dependency",
    tone: "active",
  });
  assert.deepEqual(dependencyEvidencePresentation("needs_review"), {
    label: "Needs review",
    tone: "warning",
  });
  const current = currentDependencyEvidence([
    { evaluation_state: "resolved", relationship_id: "resolved" },
    { evaluation_state: "active", relationship_id: "active" },
    { evaluation_state: "needs_review", relationship_id: "review" },
  ]);
  assert.deepEqual(
    current.map((evidence) => evidence.relationship_id),
    ["active", "review"],
  );
});

test("absent packages distinguish unmapped, empty, and failed reads", () => {
  assert.equal(
    workPackageSectionState([], { ...mappedDiagnostic, provider_ref: null, status: "not_mapped" }),
    "hidden",
  );
  assert.equal(workPackageSectionState([], mappedDiagnostic), "empty");
  assert.equal(
    workPackageSectionState([], { ...mappedDiagnostic, status: "provider_failure" }),
    "unavailable",
  );
});
