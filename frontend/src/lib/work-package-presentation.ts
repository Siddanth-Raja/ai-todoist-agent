import type {
  LinearProjectDiagnostic,
  ProjectWorkPackage,
} from "@/lib/api";

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
  return {
    label: "No executable action",
    detail: "This package has open work, but no executable leaf action.",
    tone: "muted",
  };
}
