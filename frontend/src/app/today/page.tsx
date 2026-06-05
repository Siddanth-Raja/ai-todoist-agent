"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Dumbbell,
  Flame,
  HeartHandshake,
  Moon,
  Sparkles,
  SunMedium,
  Target,
  TimerReset,
  Waves,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { apiRequest, formatDateTime, type ActivityEntry, type LifeArea, type TodayResponse } from "@/lib/api";

const lifeAreaGradients: Record<string, string> = {
  "A&M": "from-rose-300/20 via-white/[0.055] to-white/[0.035]",
  XO: "from-sky-300/20 via-white/[0.055] to-white/[0.035]",
  Freelance: "from-moss/20 via-white/[0.055] to-white/[0.035]",
  Personal: "from-gold/20 via-white/[0.055] to-white/[0.035]",
  Misc: "from-iris/20 via-white/[0.055] to-white/[0.035]",
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
  if (value === "calendar_event_created" || value === "confirmation_requested") {
    return CalendarClock;
  }
  if (value === "habit_logged") {
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
  const [lifeAreas, setLifeAreas] = useState<LifeArea[]>([]);
  const [isLifeAreasLoading, setIsLifeAreasLoading] = useState(true);
  const [lifeAreaError, setLifeAreaError] = useState<string | null>(null);
  const [lifeAreaWarnings, setLifeAreaWarnings] = useState<string[]>([]);
  const [activityEntries, setActivityEntries] = useState<ActivityEntry[]>([]);
  const [activityError, setActivityError] = useState<string | null>(null);

  useEffect(() => {
    setNow(new Date());
    apiRequest<TodayResponse>("/today")
      .then((today) => {
        setLifeAreas(today.life_areas);
        setLifeAreaWarnings(today.errors);
        setLifeAreaError(null);
      })
      .catch((error) => {
        setLifeAreaError(error instanceof Error ? error.message : "Unable to load life areas.");
      })
      .finally(() => {
        setIsLifeAreasLoading(false);
      });

    apiRequest<ActivityEntry[]>("/activity?limit=5")
      .then((entries) => {
        setActivityEntries(entries);
        setActivityError(null);
      })
      .catch((error) => {
        setActivityError(error instanceof Error ? error.message : "Unable to load activity.");
      });
  }, []);

  const hour = now.getHours();
  const GreetingIcon = getGreetingIcon(hour);
  const greeting = getGreeting(hour);
  const recentActivity = useMemo(
    () =>
      activityEntries.map((entry) => ({
        id: entry.id,
        label: formatActionType(entry.action_type),
        value: entry.title,
        detail: entry.detail || formatDateTime(entry.created_at),
        icon: iconForActivity(entry.action_type),
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
                {now.toLocaleDateString(undefined, {
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
              You have a clean window for one meaningful move before the next commitment. Keep the system light.
            </p>
          </div>

          <div className="grid min-w-0 gap-3">
            <SoftCard className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-stone-400">Current free block</p>
                  <p className="mt-2 text-3xl font-semibold text-pearl">10:30 AM-noon</p>
                  <p className="mt-2 text-sm text-stone-500">90 minutes open for focused work</p>
                </div>
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-moss/12 text-moss">
                  <Clock3 className="h-5 w-5" aria-hidden="true" />
                </span>
              </div>
            </SoftCard>

            <div className="grid gap-3 sm:grid-cols-2">
              <SoftCard className="p-5">
                <p className="text-sm text-stone-400">Next event</p>
                <p className="mt-3 text-xl font-semibold text-pearl">XO sync</p>
                <p className="mt-2 text-sm text-stone-500">12:30 PM</p>
              </SoftCard>
              <SoftCard className="p-5">
                <p className="text-sm text-stone-400">Until commitment</p>
                <p className="mt-3 text-xl font-semibold text-pearl">2h 12m</p>
                <p className="mt-2 text-sm text-stone-500">No rush</p>
              </SoftCard>
            </div>
          </div>
        </div>
      </section>

      <section className="grid min-w-0 gap-4 xl:col-span-2 xl:grid-cols-[minmax(0,1.22fr)_minmax(340px,0.78fr)]">
        <SoftCard className="relative overflow-hidden p-6 md:p-8">
          <div className="absolute right-[-6rem] top-[-6rem] h-64 w-64 rounded-full bg-moss/15 blur-3xl" />
          <div className="relative">
            <span className="mb-8 flex h-14 w-14 items-center justify-center rounded-2xl bg-pearl text-ink shadow-card">
              <Target className="h-6 w-6" aria-hidden="true" />
            </span>
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-moss">Recommendation</p>
            <h3 className="mt-4 max-w-3xl text-4xl font-semibold leading-tight tracking-normal text-pearl md:text-6xl">
              Draft the XO weekly sync agenda.
            </h3>
            <p className="mt-5 max-w-2xl text-base leading-7 text-stone-300 md:text-lg">
              One recommendation only: prep the agenda now, then enter the meeting with the next decision already framed.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <span className="inline-flex min-h-11 items-center rounded-full border border-white/10 bg-white/[0.07] px-4 text-sm text-stone-300">
                <TimerReset className="mr-2 h-4 w-4 text-moss" aria-hidden="true" />
                Fits current block
              </span>
              <span className="inline-flex min-h-11 items-center rounded-full border border-white/10 bg-white/[0.07] px-4 text-sm text-stone-300">
                <Waves className="mr-2 h-4 w-4 text-iris" aria-hidden="true" />
                Lowers afternoon friction
              </span>
            </div>
          </div>
        </SoftCard>

        <SoftCard className="p-6 md:p-7">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">Next event</p>
          <div className="mt-7 rounded-[1.5rem] bg-gradient-to-br from-coral/18 to-white/[0.04] p-5">
            <CalendarClock className="h-6 w-6 text-coral" aria-hidden="true" />
            <h3 className="mt-8 text-2xl font-semibold text-pearl">XO weekly sync</h3>
            <p className="mt-3 text-sm leading-6 text-stone-400">
              12:30 PM. Agenda prep is the only thing that materially improves this meeting.
            </p>
          </div>
          <div className="mt-4 flex items-center justify-between rounded-2xl bg-black/20 p-4">
            <span className="text-sm text-stone-400">Prep state</span>
            <span className="text-sm font-medium text-gold">Needs 20 min</span>
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
              Life areas unavailable
            </div>
            <p className="mt-2 leading-6">{lifeAreaError}</p>
          </div>
        ) : null}

        {lifeAreaWarnings.length > 0 ? (
          <div className="rounded-[1.4rem] border border-gold/25 bg-gold/10 p-4 text-sm text-gold">
            {lifeAreaWarnings.join(" ")}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {isLifeAreasLoading
            ? Array.from({ length: 5 }).map((_, index) => (
                <article
                  key={index}
                  className="min-h-60 animate-pulse rounded-[2rem] border border-white/10 bg-white/[0.055] p-5 shadow-card backdrop-blur-2xl"
                >
                  <div className="h-8 w-24 rounded-lg bg-white/10" />
                  <div className="mt-4 h-16 rounded-lg bg-white/10" />
                  <div className="mt-8 grid grid-cols-2 gap-3">
                    <div className="h-24 rounded-2xl bg-black/20" />
                    <div className="h-24 rounded-2xl bg-black/20" />
                  </div>
                </article>
              ))
            : lifeAreas.map((area) => (
                <article
                  key={area.name}
                  className={`min-h-60 rounded-[2rem] border border-white/10 bg-gradient-to-br ${gradientForLifeArea(area.name)} p-5 shadow-card backdrop-blur-2xl`}
                >
                  <div className="flex h-full flex-col justify-between gap-8">
                    <div>
                      <div className="mb-8 flex items-start justify-between gap-3">
                        <div>
                          <h4 className="text-3xl font-semibold text-pearl">{area.name}</h4>
                          <p className="mt-3 text-sm leading-6 text-stone-400">{area.description}</p>
                        </div>
                        <ArrowRight className="h-5 w-5 text-stone-500" aria-hidden="true" />
                      </div>
                      <p className="rounded-full border border-white/10 bg-black/20 px-3 py-2 text-sm text-stone-300">
                        {area.status}
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      {metricsForLifeArea(area).map((metric) => (
                        <div key={metric.label} className="rounded-2xl bg-black/20 p-4">
                          <p className="text-xs uppercase tracking-[0.18em] text-stone-500">{metric.label}</p>
                          <p className="mt-2 text-3xl font-semibold text-pearl">{metric.value}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </article>
              ))}
        </div>
      </section>

      <section className="grid min-w-0 gap-4 xl:col-span-2 xl:grid-cols-[0.95fr_1.05fr]">
        <SoftCard className="p-6 md:p-8">
          <div className="mb-8 flex items-start justify-between gap-4">
            <SectionTitle eyebrow="Accountability" title="Promises made visible" />
            <HeartHandshake className="h-6 w-6 text-moss" aria-hidden="true" />
          </div>

          <div className="space-y-3">
            <div className="rounded-[1.4rem] bg-black/20 p-5">
              <div className="flex items-center gap-3">
                <Dumbbell className="h-5 w-5 text-moss" aria-hidden="true" />
                <p className="font-medium text-pearl">Gym status</p>
              </div>
              <p className="mt-3 text-sm text-stone-400">Scheduled for 6:15 PM. Keep dinner light.</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-[1.4rem] bg-black/20 p-5">
                <Flame className="h-5 w-5 text-gold" aria-hidden="true" />
                <p className="mt-5 text-2xl font-semibold text-pearl">6 days</p>
                <p className="mt-1 text-sm text-stone-500">Planning streak</p>
              </div>
              <div className="rounded-[1.4rem] bg-black/20 p-5">
                <CircleAlert className="h-5 w-5 text-coral" aria-hidden="true" />
                <p className="mt-5 text-2xl font-semibold text-pearl">1</p>
                <p className="mt-1 text-sm text-stone-500">Missed commitment</p>
              </div>
            </div>
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
