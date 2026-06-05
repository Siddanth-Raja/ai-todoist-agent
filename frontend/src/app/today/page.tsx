"use client";

import { useEffect, useState } from "react";
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

type LifeArea = {
  name: string;
  subtitle: string;
  tasks: number;
  overdue: number;
  status: string;
  gradient: string;
};

type ActivityItem = {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
};

const lifeAreas: LifeArea[] = [
  {
    name: "A&M",
    subtitle: "Shared life, home rhythm, relationship care",
    tasks: 5,
    overdue: 1,
    status: "Needs a gentle check-in",
    gradient: "from-rose-300/20 via-white/[0.055] to-white/[0.035]",
  },
  {
    name: "XO",
    subtitle: "Leadership loops, decisions, operating cadence",
    tasks: 8,
    overdue: 2,
    status: "Two decisions waiting",
    gradient: "from-sky-300/20 via-white/[0.055] to-white/[0.035]",
  },
  {
    name: "Freelance",
    subtitle: "Client delivery, cashflow, pipeline",
    tasks: 4,
    overdue: 0,
    status: "Clear for deep work",
    gradient: "from-moss/20 via-white/[0.055] to-white/[0.035]",
  },
  {
    name: "Personal",
    subtitle: "Health, recovery, errands, maintenance",
    tasks: 6,
    overdue: 1,
    status: "One loose end",
    gradient: "from-gold/20 via-white/[0.055] to-white/[0.035]",
  },
];

const recentActivity: ActivityItem[] = [
  {
    label: "Completed",
    value: "3 tasks",
    detail: "Inbox triage, invoice draft, calendar cleanup",
    icon: CheckCircle2,
  },
  {
    label: "Created",
    value: "1 event",
    detail: "Freelance review block placed after lunch",
    icon: CalendarClock,
  },
  {
    label: "Adjusted",
    value: "2 changes",
    detail: "XO prep moved into the current open block",
    icon: Activity,
  },
];

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

  useEffect(() => {
    setNow(new Date());
  }, []);

  const hour = now.getHours();
  const GreetingIcon = getGreetingIcon(hour);
  const greeting = getGreeting(hour);

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

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {lifeAreas.map((area) => (
            <article
              key={area.name}
              className={`min-h-60 rounded-[2rem] border border-white/10 bg-gradient-to-br ${area.gradient} p-5 shadow-card backdrop-blur-2xl`}
            >
              <div className="flex h-full flex-col justify-between gap-8">
                <div>
                  <div className="mb-8 flex items-start justify-between gap-3">
                    <div>
                      <h4 className="text-3xl font-semibold text-pearl">{area.name}</h4>
                      <p className="mt-3 text-sm leading-6 text-stone-400">{area.subtitle}</p>
                    </div>
                    <ArrowRight className="h-5 w-5 text-stone-500" aria-hidden="true" />
                  </div>
                  <p className="rounded-full border border-white/10 bg-black/20 px-3 py-2 text-sm text-stone-300">
                    {area.status}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-2xl bg-black/20 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Tasks</p>
                    <p className="mt-2 text-3xl font-semibold text-pearl">{area.tasks}</p>
                  </div>
                  <div className="rounded-2xl bg-black/20 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Overdue</p>
                    <p className="mt-2 text-3xl font-semibold text-pearl">{area.overdue}</p>
                  </div>
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
            {recentActivity.map((item) => {
              const Icon = item.icon;

              return (
                <article key={item.label} className="flex gap-4 rounded-[1.4rem] bg-black/20 p-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-white/[0.07] text-pearl">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <h4 className="text-sm font-medium text-stone-400">{item.label}</h4>
                      <p className="text-lg font-semibold text-pearl">{item.value}</p>
                    </div>
                    <p className="mt-1 text-sm leading-6 text-stone-500">{item.detail}</p>
                  </div>
                </article>
              );
            })}
          </div>
        </SoftCard>
      </section>
    </div>
  );
}
