"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  CircleAlert,
  Clock3,
  HeartHandshake,
  Moon,
  Sparkles,
  SunMedium,
  Target,
  TimerReset,
  Waves,
  ExternalLink,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  formatDateTime,
  type ActivityEntry,
  type LifeArea,
  type TodayResponse,
} from "@/lib/api";
import {
  todayMustDoItemLabel,
  todayMustDoPresentation,
  todayProjectCardPresentation,
  todayRecommendationBadge,
} from "@/lib/today-projection-presentation";
import {
  LIFE_AREA_GRID_CLASS,
  todayRecommendationPresentation,
} from "@/lib/surface-hierarchy-presentation";
import { useRetainedApiQuery } from "@/lib/use-retained-api-query";
import {
  RealityEvidenceCard,
  RealityEvidenceDisclosure,
} from "@/components/reality-evidence";

const lifeAreaGradients: Record<string, string> = {
  "A&M": "from-rose-300/20 via-white/[0.055] to-white/[0.035]",
  XO: "from-sky-300/20 via-white/[0.055] to-white/[0.035]",
  Nebulo: "from-iris/20 via-white/[0.055] to-white/[0.035]",
  Freelance: "from-moss/20 via-white/[0.055] to-white/[0.035]",
  Personal: "from-gold/20 via-white/[0.055] to-white/[0.035]",
  Misc: "from-iris/20 via-white/[0.055] to-white/[0.035]",
};

const projectHrefByLifeArea: Record<string, string> = {
  "A&M": "/projects/am",
  XO: "/projects/xo",
  Nebulo: "/projects/nebulo",
  Freelance: "/projects/freelance",
  Personal: "/projects/personal",
  Misc: "/projects",
};

function getGreeting(hour: number) {
  if (hour < 12) {
    return "Good morning";
  }

  if (hour < 17) {
    return "Good afternoon";
  }

  return "Good evening";
}

function getGreetingIcon(hour: number) {
  if (hour < 6 || hour >= 19) {
    return Moon;
  }

  return SunMedium;
}

function formatActionType(value: string) {
  return value.replaceAll("_", " ");
}

function iconForActivity(value: string): LucideIcon {
  if (value === "task_created") {
    return CheckCircle2;
  }
  if (
    value === "calendar_event_created" ||
    value === "calendar_event_updated" ||
    value === "confirmation_requested" ||
    value === "confirmation_completed" ||
    value === "confirmation_cancelled"
  ) {
    return CalendarClock;
  }
  if (value === "habit_logged" || value.startsWith("memory_")) {
    return HeartHandshake;
  }
  return Activity;
}

function gradientForLifeArea(name: string) {
  return lifeAreaGradients[name] ?? lifeAreaGradients.Misc;
}

function metricsForLifeArea(area: LifeArea) {
  const metrics = [
    { label: "Tasks", value: area.task_count },
    { label: "Overdue", value: area.overdue_count },
  ];

  if (area.today_count > 0) {
    metrics.push({ label: "Today", value: area.today_count });
  }

  if (area.high_priority_count > 0) {
    metrics.push({ label: "High", value: area.high_priority_count });
  }

  return metrics;
}

function formatMinutes(minutes: number) {
  if (minutes < 1) {
    return "Now";
  }
  if (minutes < 60) {
    return `${minutes} min`;
  }

  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function formatObligationDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function SoftCard({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-[2rem] border border-white/10 bg-white/[0.055] shadow-card backdrop-blur-2xl ${className}`}>
      {children}
    </div>
  );
}

function SectionTitle({
  eyebrow,
  title,
  detail,
}: {
  eyebrow: string;
  title: string;
  detail?: string;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">{eyebrow}</p>
      <h3 className="mt-2 text-2xl font-semibold tracking-normal text-pearl md:text-3xl">{title}</h3>
      {detail ? <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-400">{detail}</p> : null}
    </div>
  );
}

export default function TodayPage() {
  const [now, setNow] = useState(() => new Date());
  const todayQuery = useRetainedApiQuery<TodayResponse>("/today");
  const activityQuery = useRetainedApiQuery<ActivityEntry[]>("/activity?limit=5");
  const todayData = todayQuery.data;
  const lifeAreas: LifeArea[] = todayData?.life_areas ?? [];
  const lifeAreaWarnings = todayData?.errors ?? [];
  const lifeAreaError = todayQuery.initialError ?? todayQuery.refreshError;
  const activityEntries = activityQuery.data ?? [];
  const activityError = activityQuery.initialError ?? activityQuery.refreshError;
  const isLifeAreasLoading = todayQuery.isInitialLoading;

  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 30000);

    return () => window.clearInterval(timer);
  }, []);

  const hour = now.getHours();
  const GreetingIcon = getGreetingIcon(hour);
  const greeting = getGreeting(hour);
  const nextEvent = todayData?.next_event ?? null;
  const currentBlock = todayData?.current_free_block ?? null;
  const commitments = todayData?.today_remaining_events ?? [];
  const minutesUntilNext = todayData?.minutes_until_next_event ?? null;
  const mustDo = todayData?.must_do ?? null;
  const mustDoPresentation = mustDo ? todayMustDoPresentation(mustDo) : null;
  const recommendation = todayData?.recommendation ?? null;
  const recommendationBadge = todayRecommendationBadge(recommendation);
  const recommendationPresentation = todayRecommendationPresentation(recommendation);
  const shouldPrepare = recommendation?.type === "prepare";
  const isTodayLoading = !todayData && isLifeAreasLoading;
  const isTodayUnavailable = !todayData && !isLifeAreasLoading;
  const recentActivity = useMemo(
    () =>
      activityEntries.map((entry) => ({
        id: entry.id,
        label: formatActionType(entry.type || entry.action_type),
        value: entry.title,
        detail: [entry.source, entry.description || entry.detail || formatDateTime(entry.created_at)]
          .filter(Boolean)
          .join(" - "),
        icon: iconForActivity(entry.type || entry.action_type),
      })),
    [activityEntries],
  );

  return (
    <div className="mx-auto grid w-[calc(100vw-2rem)] min-w-0 max-w-full grid-cols-1 gap-6 overflow-x-hidden pb-4 sm:w-full sm:max-w-[860px] md:max-w-[940px] md:gap-8 xl:max-w-[1440px] xl:grid-cols-2">
      <section className="relative min-w-0 overflow-hidden rounded-[2.4rem] border border-white/10 bg-[radial-gradient(circle_at_20%_0%,rgba(246,241,232,0.2),transparent_28rem),linear-gradient(135deg,rgba(255,255,255,0.13),rgba(255,255,255,0.045)_52%,rgba(183,167,255,0.11))] p-5 shadow-soft md:p-8 lg:p-10 xl:col-span-2">
        <div className="absolute right-[-7rem] top-[-7rem] h-72 w-72 rounded-full bg-moss/15 blur-3xl" />
        <div className="absolute bottom-[-9rem] left-8 h-72 w-72 rounded-full bg-coral/10 blur-3xl" />

        <div className="relative grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.12fr)_minmax(340px,0.88fr)] xl:items-end">
          <div className="min-h-[22rem] min-w-0 rounded-[2rem] border border-white/10 bg-black/15 p-5 md:p-7">
            <div className="mb-10 flex flex-col items-start gap-3 sm:mb-12 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <span className="inline-flex min-h-10 items-center rounded-full border border-white/10 bg-white/[0.07] px-3 text-xs font-medium text-stone-300">
                <GreetingIcon className="mr-2 h-4 w-4 text-moss" aria-hidden="true" />
                Personal operating system
              </span>
              <span className="text-sm text-stone-400" suppressHydrationWarning>
                {todayData?.now_display ?? now.toLocaleDateString(undefined, {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                })}
              </span>
            </div>

            <h3
              className="max-w-3xl break-words text-5xl font-semibold leading-[0.95] tracking-normal text-pearl md:text-7xl"
              suppressHydrationWarning
            >
              {greeting} Siddanth.
            </h3>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-stone-300">
              {isTodayLoading
                ? "Reading live calendar data for the rest of today."
                : isTodayUnavailable
                  ? "Live Today data is unavailable until the backend connection is configured."
                : nextEvent
                ? `Your next live calendar commitment is ${nextEvent.title} at ${nextEvent.start_display}.`
                : "No blocking calendar commitments remain today."}
            </p>
          </div>

          <div className="grid min-w-0 gap-3">
            <SoftCard className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-stone-400">{shouldPrepare ? "Prepare" : "Current free block"}</p>
                  <p className="mt-2 text-3xl font-semibold text-pearl">
                    {isTodayLoading
                      ? "Loading live calendar"
                      : isTodayUnavailable
                        ? "Today unavailable"
                      : shouldPrepare
                      ? nextEvent?.title ?? "Prepare"
                      : currentBlock?.time_range_display ?? "No meaningful block"}
                  </p>
                  <p className="mt-2 text-sm text-stone-500">
                    {isTodayLoading
                      ? "Calculating from now through end of day."
                      : isTodayUnavailable
                        ? "Add backend URL and API key in Settings to calculate the live day."
                      : shouldPrepare
                      ? recommendation?.detail ?? "Focus on preparation for the next commitment."
                      : currentBlock
                        ? `${currentBlock.duration_minutes} minutes open${
                            currentBlock.low_usefulness ? ", low usefulness" : ""
                          }`
                        : "The next commitment is too close for meaningful work."}
                  </p>
                </div>
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-moss/12 text-moss">
                  {shouldPrepare ? (
                    <CalendarClock className="h-5 w-5" aria-hidden="true" />
                  ) : (
                    <Clock3 className="h-5 w-5" aria-hidden="true" />
                  )}
                </span>
              </div>
            </SoftCard>

            <div className="grid gap-3 sm:grid-cols-2">
              <SoftCard className="p-5">
                <p className="text-sm text-stone-400">Next event</p>
                <p className="mt-3 text-xl font-semibold text-pearl">
                  {isTodayLoading ? "Loading" : isTodayUnavailable ? "Unavailable" : nextEvent?.title ?? "None remaining"}
                </p>
                <p className="mt-2 text-sm text-stone-500">
                  {isTodayLoading
                    ? "Checking live Calendar"
                    : isTodayUnavailable
                      ? "Backend connection needed"
                      : nextEvent?.time_range_display ?? "Calendar is clear"}
                </p>
              </SoftCard>
              <SoftCard className="p-5">
                <p className="text-sm text-stone-400">Until commitment</p>
                <p className="mt-3 text-xl font-semibold text-pearl">
                  {isTodayLoading
                    ? "Loading"
                    : isTodayUnavailable
                      ? "Unavailable"
                      : minutesUntilNext === null ? "No next event" : formatMinutes(minutesUntilNext)}
                </p>
                <p className="mt-2 text-sm text-stone-500">
                  {isTodayLoading
                    ? "Using current time"
                    : isTodayUnavailable
                      ? "No live calculation"
                    : minutesUntilNext !== null && minutesUntilNext <= 30
                    ? "Prep/travel only"
                    : minutesUntilNext !== null && minutesUntilNext <= 60
                      ? "Prepare now"
                      : "Room to work"}
                </p>
              </SoftCard>
            </div>
          </div>
        </div>
      </section>

      <section className="min-w-0 space-y-5 xl:col-span-2">
        <SectionTitle
          eyebrow="Must do"
          title="Overdue and due today"
          detail="Concrete obligations are protected here. They do not compete with the separate recommended-work ranking below."
        />

        {mustDoPresentation?.warning ? (
          <div className="rounded-[1.4rem] border border-gold/25 bg-gold/10 p-4 text-sm text-gold">
            <div className="flex items-center gap-2 font-medium">
              <CircleAlert className="h-4 w-4" aria-hidden="true" />
              Must do is {mustDo?.state}
            </div>
            <p className="mt-2 leading-6">{mustDoPresentation.warning}</p>
          </div>
        ) : null}

        <SoftCard className="overflow-hidden border-coral/20 bg-[linear-gradient(135deg,rgba(255,139,116,0.13),rgba(255,255,255,0.045)_52%,rgba(255,205,126,0.08))] p-5 md:p-7">
          {isTodayLoading ? (
            <div className="h-28 animate-pulse rounded-[1.4rem] bg-white/[0.06]" />
          ) : isTodayUnavailable ? (
            <div className="rounded-[1.4rem] border border-coral/25 bg-coral/10 p-5">
              <p className="font-medium text-coral">Must do unavailable</p>
              <p className="mt-2 text-sm leading-6 text-stone-400">
                Connect the backend in Settings before Today can read live obligations.
              </p>
            </div>
          ) : mustDo?.items.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {mustDo.items.map((obligation) => {
                const content = (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                        obligation.urgency === "overdue"
                          ? "bg-coral/15 text-coral"
                          : "bg-gold/15 text-gold"
                      }`}>
                        {todayMustDoItemLabel(obligation)}
                      </span>
                      <span className="text-xs uppercase tracking-[0.16em] text-stone-500">
                        {obligation.provider}
                      </span>
                    </div>
                    <h3 className="mt-4 break-words text-2xl font-semibold text-pearl">
                      {obligation.title}
                    </h3>
                    <p className="mt-2 text-sm text-stone-400">
                      Due {formatObligationDate(obligation.due_date)}
                    </p>
                    {obligation.reality ? (
                      <RealityEvidenceDisclosure item={obligation.reality} />
                    ) : null}
                    {obligation.provider_url ? (
                      <a
                        href={obligation.provider_url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-flex min-h-11 items-center gap-1.5 text-xs text-moss hover:text-pearl"
                      >
                        Open provider record
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      </a>
                    ) : null}
                  </>
                );
                return (
                  <article
                    key={`${obligation.provider}:${obligation.provider_record_id}`}
                    className="rounded-[1.4rem] border border-white/10 bg-black/20 p-5"
                  >
                    {content}
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="flex items-start gap-3 rounded-[1.4rem] bg-black/20 p-5">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-moss" aria-hidden="true" />
              <div>
                <p className="font-medium text-pearl">{mustDoPresentation?.emptyTitle}</p>
                <p className="mt-2 text-sm leading-6 text-stone-400">
                  {mustDo?.state === "available"
                    ? "Connected work providers have no executable overdue or due-today items."
                    : "One or more work providers are unavailable, so Today is not treating this as a confirmed empty state."}
                </p>
              </div>
            </div>
          )}
        </SoftCard>
      </section>

      {todayData?.reality_attention.length ? (
        <section className="min-w-0 space-y-5 xl:col-span-2">
          <SectionTitle
            eyebrow="Needs review"
            title="Actionable shared reality"
            detail="Exactly linked mismatches are reviewable now. Provider truth remains unchanged until a separate exact confirmation succeeds."
          />
          <SoftCard className="grid gap-3 p-5 md:grid-cols-2 md:p-7">
            {todayData.reality_attention.map((item) => (
              <RealityEvidenceCard key={item.reality_item_id} item={item} />
            ))}
          </SoftCard>
        </section>
      ) : null}

      <section
        className="grid min-w-0 gap-4 xl:col-span-2 xl:grid-cols-[minmax(0,1.22fr)_minmax(320px,0.78fr)]"
        data-recommendation-prominence={recommendationPresentation.prominence}
      >
        <SoftCard className={`relative overflow-hidden p-6 md:p-8 ${recommendationPresentation.cardClassName}`}>
          <div className="relative">
            <span className={`mb-6 flex items-center justify-center rounded-2xl shadow-card ${recommendationPresentation.iconClassName}`}>
              <Target className="h-6 w-6" aria-hidden="true" />
            </span>
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-moss">
              {recommendationPresentation.label}
            </p>
            <h3 className={`mt-4 max-w-3xl font-semibold leading-tight tracking-normal text-pearl ${recommendationPresentation.headingClassName}`}>
              {recommendation?.title ?? (isTodayUnavailable ? "Today unavailable" : "Loading today")}
            </h3>
            <p className="mt-4 max-w-2xl text-base leading-7 text-stone-300">
              {recommendation?.detail ??
                (isTodayUnavailable
                  ? "Connect Settings so the backend can read live Calendar and Todoist data."
                  : "Reading live calendar and Todoist context.")}
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <span className="inline-flex min-h-11 items-center rounded-full border border-white/10 bg-white/[0.07] px-4 text-sm text-stone-300">
                <TimerReset className="mr-2 h-4 w-4 text-moss" aria-hidden="true" />
                {currentBlock ? `${currentBlock.duration_minutes} min block` : "No work block"}
              </span>
              <span className="inline-flex min-h-11 items-center rounded-full border border-white/10 bg-white/[0.07] px-4 text-sm text-stone-300">
                <Waves className="mr-2 h-4 w-4 text-iris" aria-hidden="true" />
                {recommendationBadge}
              </span>
            </div>
            {recommendation?.reality ? (
              <RealityEvidenceDisclosure item={recommendation.reality} />
            ) : null}
          </div>
        </SoftCard>

        <SoftCard className="p-6 md:p-7">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">Next event</p>
          <div className="mt-7 rounded-[1.5rem] bg-gradient-to-br from-coral/18 to-white/[0.04] p-5">
            <CalendarClock className="h-6 w-6 text-coral" aria-hidden="true" />
            <h3 className="mt-8 text-2xl font-semibold text-pearl">
              {isTodayUnavailable ? "Unavailable" : nextEvent?.title ?? "No events left"}
            </h3>
            <p className="mt-3 text-sm leading-6 text-stone-400">
              {isTodayUnavailable
                ? "Live calendar data could not be loaded."
                : nextEvent
                ? `${nextEvent.time_range_display}. ${minutesUntilNext ?? 0} minutes away.`
                : "The rest of today has no future blocking calendar commitments."}
            </p>
          </div>
          <div className="mt-4 flex items-center justify-between rounded-2xl bg-black/20 p-4">
            <span className="text-sm text-stone-400">State</span>
            <span className="text-sm font-medium text-gold">
              {isTodayUnavailable ? "Needs connection" : shouldPrepare ? "Prepare" : nextEvent ? "Before next event" : "Open"}
            </span>
          </div>
        </SoftCard>
      </section>

      <section className="min-w-0 space-y-5 xl:col-span-2">
        <SectionTitle
          eyebrow="Life Areas"
          title="Four lanes, one calm scan"
          detail="Enough signal to know where attention is needed, without turning your life into a spreadsheet."
        />

        {lifeAreaError ? (
          <div className="rounded-[1.4rem] border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
            <div className="flex items-center gap-2 font-medium">
              <CircleAlert className="h-4 w-4" aria-hidden="true" />
              {todayData ? "Today refresh failed; showing retained state" : "Life areas unavailable"}
            </div>
            <p className="mt-2 leading-6">{lifeAreaError}</p>
          </div>
        ) : null}

        {lifeAreaWarnings.length > 0 ? (
          <div className="rounded-[1.4rem] border border-gold/25 bg-gold/10 p-4 text-sm text-gold">
            {lifeAreaWarnings.join(" ")}
          </div>
        ) : null}

        <div className={LIFE_AREA_GRID_CLASS} data-life-area-count={lifeAreas.length}>
          {isLifeAreasLoading
            ? Array.from({ length: 6 }).map((_, index) => (
                <article
                  key={index}
                  className="animate-pulse rounded-[1.5rem] border border-white/10 bg-white/[0.055] p-5 shadow-card backdrop-blur-2xl"
                >
                  <div className="h-8 w-24 rounded-lg bg-white/10" />
                  <div className="mt-4 h-12 rounded-lg bg-white/10" />
                  <div className="mt-5 h-10 rounded-xl bg-black/20" />
                </article>
              ))
            : lifeAreas.map((area) => {
                const projection = todayProjectCardPresentation(area);
                return (
                  <Link
                    key={area.name}
                    href={projectHrefByLifeArea[area.name] ?? "/projects"}
                    className={`rounded-[1.5rem] border border-white/10 bg-gradient-to-br ${gradientForLifeArea(area.name)} p-5 shadow-card backdrop-blur-2xl transition hover:border-white/20`}
                  >
                    <div className="flex h-full flex-col justify-between gap-5">
                      <div>
                        <div className="mb-5 flex items-start justify-between gap-3">
                          <div>
                            <h4 className="text-2xl font-semibold text-pearl">{area.name}</h4>
                            <p className="mt-2 text-sm leading-6 text-stone-400">{area.description}</p>
                          </div>
                          <ArrowRight className="h-5 w-5 text-stone-500" aria-hidden="true" />
                        </div>
                        <p className="inline-flex rounded-full border border-white/10 bg-black/20 px-3 py-1.5 text-xs font-medium text-stone-300">
                          {projection.status}
                        </p>
                        {projection.nextMove ? (
                          <p className="mt-3 line-clamp-2 text-sm font-medium leading-6 text-stone-300">
                            {projection.nextMove}
                          </p>
                        ) : null}
                        {projection.failure ? (
                          <p className="mt-3 text-sm leading-6 text-gold">
                            {projection.failure}
                          </p>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-white/10 pt-4">
                        {metricsForLifeArea(area).map((metric) => (
                          <p key={metric.label} className="text-xs uppercase tracking-[0.16em] text-stone-500">
                            <span className="mr-1.5 text-base font-semibold tracking-normal text-pearl">{metric.value}</span>
                            {metric.label}
                          </p>
                        ))}
                      </div>
                    </div>
                  </Link>
                );
              })}
        </div>
      </section>

      <section className="grid min-w-0 gap-4 xl:col-span-2 xl:grid-cols-[0.95fr_1.05fr]">
        <SoftCard className="p-6 md:p-8">
          <div className="mb-8 flex items-start justify-between gap-4">
            <SectionTitle eyebrow="Calendar" title="Remaining commitments" />
            <HeartHandshake className="h-6 w-6 text-moss" aria-hidden="true" />
          </div>

          <div className="space-y-3">
            {commitments.length === 0 ? (
              <div className="rounded-[1.4rem] bg-black/20 p-5">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="h-5 w-5 text-moss" aria-hidden="true" />
                  <p className="font-medium text-pearl">No future events today</p>
                </div>
                <p className="mt-3 text-sm text-stone-400">
                  Today has no remaining live calendar commitments.
                </p>
              </div>
            ) : (
              commitments.map((event) => (
                <article key={event.id ?? `${event.title}-${event.start}`} className="rounded-[1.4rem] bg-black/20 p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="break-words font-medium text-pearl">{event.title}</p>
                      <p className="mt-2 text-sm text-stone-400">{event.time_range_display}</p>
                    </div>
                    <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1 text-xs capitalize text-stone-400">
                      {event.event_category}
                    </span>
                  </div>
                  {event.location ? (
                    <p className="mt-3 break-words text-sm text-stone-500">{event.location}</p>
                  ) : null}
                </article>
              ))
            )}
          </div>
        </SoftCard>

        <SoftCard className="p-6 md:p-8">
          <SectionTitle eyebrow="Recent Activity" title="Quiet progress log" />

          <div className="mt-8 space-y-4">
            {activityError ? (
              <div className="rounded-[1.4rem] border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
                {activityError}
              </div>
            ) : recentActivity.length === 0 ? (
              <div className="rounded-[1.4rem] bg-black/20 p-4 text-sm text-stone-500">
                No activity recorded yet.
              </div>
            ) : (
              recentActivity.map((item) => {
                const Icon = item.icon;

                return (
                  <article key={item.id} className="flex gap-4 rounded-[1.4rem] bg-black/20 p-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-white/[0.07] text-pearl">
                      <Icon className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <h4 className="text-sm font-medium capitalize text-stone-400">{item.label}</h4>
                        <p className="break-words text-lg font-semibold text-pearl">{item.value}</p>
                      </div>
                      <p className="mt-1 break-words text-sm leading-6 text-stone-500">{item.detail}</p>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </SoftCard>
      </section>
    </div>
  );
}
