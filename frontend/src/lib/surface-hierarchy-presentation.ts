import type { TodayRecommendation } from "@/lib/api";

export type RecommendationProminence = "primary" | "secondary" | "supporting";

export type RecommendationPresentation = {
  prominence: RecommendationProminence;
  label: string;
  cardClassName: string;
  headingClassName: string;
  iconClassName: string;
};

const EXECUTABLE_SIGNALS = new Set([
  "due_urgency",
  "usable_free_block_fit",
  "energy_fit",
  "upcoming_commitment",
]);

export const LIFE_AREA_GRID_CLASS =
  "life-area-grid grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr))]";

export function todayRecommendationPresentation(
  recommendation: TodayRecommendation | null,
): RecommendationPresentation {
  const hasPositiveExecutableEvidence = Boolean(
    recommendation?.evidence.some(
      (evidence) =>
        EXECUTABLE_SIGNALS.has(evidence.signal) && evidence.score_delta > 0,
    ),
  );
  const isPrimary =
    recommendation?.source === "calendar" ||
    recommendation?.contextual_override === true ||
    hasPositiveExecutableEvidence;
  const isSupporting =
    !recommendation ||
    recommendation.source === "fallback" ||
    !recommendation.provider ||
    !recommendation.provider_record_id;

  if (isPrimary) {
    return {
      prominence: "primary",
      label: "High-specificity recommendation",
      cardClassName: "border-moss/25 bg-white/[0.065]",
      headingClassName: "text-4xl md:text-5xl",
      iconClassName: "h-14 w-14 bg-pearl text-ink",
    };
  }

  if (isSupporting) {
    return {
      prominence: "supporting",
      label: "Recommendation context",
      cardClassName: "border-white/10 bg-black/15",
      headingClassName: "text-2xl md:text-3xl",
      iconClassName: "h-11 w-11 bg-white/[0.07] text-stone-300",
    };
  }

  return {
    prominence: "secondary",
    label: "Recommended work",
    cardClassName: "border-white/10 bg-white/[0.045]",
    headingClassName: "text-3xl md:text-4xl",
    iconClassName: "h-12 w-12 bg-white/[0.08] text-moss",
  };
}

export function calendarDayDensity(eventCount: number): "compact" | "timeline" {
  return eventCount === 0 ? "compact" : "timeline";
}

export function calendarDayEventHeightRem(
  startMinutes: number,
  durationMinutes: number,
): number {
  const timelineStart = 6 * 60;
  const timelineEnd = 23 * 60;
  const visibleStart = Math.min(
    timelineEnd,
    Math.max(timelineStart, startMinutes),
  );
  const visibleMinutes = Math.min(
    Math.max(30, durationMinutes),
    Math.max(30, timelineEnd - visibleStart),
  );
  return Math.max(3, (visibleMinutes / 60) * 4);
}

export function calendarWeekDensity(
  blockingCount: number,
  informationalCount: number,
): "compact" | "calendar" {
  return blockingCount + informationalCount === 0 ? "compact" : "calendar";
}
