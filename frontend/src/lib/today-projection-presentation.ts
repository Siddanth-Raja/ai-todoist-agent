import type { LifeArea, TodayRecommendation } from "@/lib/api";

export type TodayProjectCardPresentation = {
  status: string;
  nextMove: string | null;
  failure: string | null;
};

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
