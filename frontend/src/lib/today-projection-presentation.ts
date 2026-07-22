import type {
  LifeArea,
  TodayMustDo,
  TodayObligation,
  TodayRecommendation,
} from "@/lib/api";

export type TodayProjectCardPresentation = {
  status: string;
  nextMove: string | null;
  failure: string | null;
};

export type TodayMustDoPresentation = {
  emptyTitle: string;
  warning: string | null;
};

export function todayMustDoPresentation(
  mustDo: TodayMustDo,
): TodayMustDoPresentation {
  const warning = mustDo.errors.length > 0 ? mustDo.errors.join(" ") : null;
  return {
    emptyTitle:
      mustDo.state === "unavailable"
        ? "Must do data unavailable"
        : mustDo.state === "degraded"
          ? "No known overdue or due-today obligations"
          : "No overdue or due-today obligations",
    warning,
  };
}

export function todayMustDoItemLabel(
  obligation: Pick<TodayObligation, "urgency" | "days_overdue">,
): string {
  if (obligation.urgency === "due_today") {
    return "Due today";
  }
  return `${obligation.days_overdue} day${obligation.days_overdue === 1 ? "" : "s"} overdue`;
}

export function todayProjectCardPresentation(
  area: LifeArea,
): TodayProjectCardPresentation {
  return {
    status: area.status,
    nextMove: area.next_recommendation ?? null,
    failure: area.degraded
      ? area.provider_message ?? "Project provider state is unavailable."
      : null,
  };
}

export function todayRecommendationBadge(
  recommendation: TodayRecommendation | null,
): string {
  if (recommendation?.source === "calendar") {
    return "Calendar-first";
  }
  if (recommendation?.contextual_override) {
    return "Contextual shared override";
  }
  if (recommendation?.source === "shared_recommendation") {
    return "Shared recommendation";
  }
  return "Shared intelligence state";
}
