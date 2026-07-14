import type {
  EvaluatedDependencyEvidence,
  LinearProjectDiagnostic,
  ProjectWorkPackage,
} from "@/lib/api";

export function currentDependencyEvidence(
  evidence: EvaluatedDependencyEvidence[],
): EvaluatedDependencyEvidence[] {
  return evidence.filter((relationship) => relationship.evaluation_state !== "resolved");
}

export function dependencyEvidencePresentation(
  state: EvaluatedDependencyEvidence["evaluation_state"],
): { label: string; tone: "active" | "warning" | "resolved" } {
  if (state === "active") {
    return { label: "Active dependency", tone: "active" };
  }
  if (state === "needs_review") {
    return { label: "Needs review", tone: "warning" };
  }
  return { label: "Resolved", tone: "resolved" };
}

export type WorkPackageSectionState =
  | "hidden"
  | "options"
  | "empty"
  | "unavailable";

export function workPackageSectionState(
  packages: ProjectWorkPackage[],
  diagnostic: LinearProjectDiagnostic | null,
): WorkPackageSectionState {
  if (!diagnostic?.provider_ref) {
    return "hidden";
  }
  if (packages.length > 0) {
    return "options";
  }
  return diagnostic.status === "connected" ? "empty" : "unavailable";
}

export function packageAvailabilityPresentation(
  availability: ProjectWorkPackage["availability_state"],
): { label: string; detail: string; tone: "available" | "warning" | "muted" } {
  if (availability === "available") {
    return {
      label: "Available",
      detail: "An executable next action is ready.",
      tone: "available",
    };
  }
  if (availability === "explicitly_blocked") {
    return {
      label: "Explicitly blocked",
      detail: "Every open action in this package is explicitly blocked in Linear.",
      tone: "warning",
    };
  }
  if (availability === "needs_review") {
    return {
      label: "Needs review",
      detail: "Dependency evidence is incomplete or canceled and must be reviewed before proceeding.",
      tone: "warning",
    };
  }
  return {
    label: "No executable action",
    detail: "This package has open work, but no executable leaf action.",
    tone: "muted",
  };
}
