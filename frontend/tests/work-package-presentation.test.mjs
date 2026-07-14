import assert from "node:assert/strict";
import test from "node:test";

import {
  currentDependencyEvidence,
  dependencyEvidencePresentation,
  packageAvailabilityPresentation,
  workPackageSectionState,
} from "../src/lib/work-package-presentation.ts";

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
