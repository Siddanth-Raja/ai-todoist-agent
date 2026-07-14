import assert from "node:assert/strict";
import test from "node:test";

import {
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
