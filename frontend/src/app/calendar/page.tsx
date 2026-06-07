"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Clock3,
  ExternalLink,
  MapPin,
  RefreshCw,
  Users,
} from "lucide-react";
import {
  apiRequest,
  formatDateTime,
  formatTime,
  type CalendarEvent,
  type CalendarResponse,
} from "@/lib/api";

type CalendarView = "day" | "week" | "upcoming";
type ProjectLabel = "A&M" | "XO" | "Nebulo" | "Freelance" | "Personal" | "Misc";

const projectLabels: ProjectLabel[] = ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"];

const projectStyles: Record<ProjectLabel, { chip: string; dot: string; rail: string; block: string }> = {
  "A&M": {
    chip: "border-rose-300/35 bg-rose-300/10 text-rose-200",
    dot: "bg-rose-300",
    rail: "border-l-rose-300",
    block: "border-rose-300/30 bg-rose-300/12",
  },
  XO: {
    chip: "border-sky-300/35 bg-sky-300/10 text-sky-200",
    dot: "bg-sky-300",
    rail: "border-l-sky-300",
    block: "border-sky-300/30 bg-sky-300/12",
  },
  Nebulo: {
    chip: "border-iris/40 bg-iris/10 text-iris",
    dot: "bg-iris",
    rail: "border-l-iris",
    block: "border-iris/30 bg-iris/12",
  },
  Freelance: {
    chip: "border-moss/35 bg-moss/10 text-moss",
    dot: "bg-moss",
    rail: "border-l-moss",
    block: "border-moss/30 bg-moss/12",
  },
  Personal: {
    chip: "border-gold/40 bg-gold/10 text-gold",
    dot: "bg-gold",
    rail: "border-l-gold",
    block: "border-gold/30 bg-gold/12",
  },
  Misc: {
    chip: "border-stone-500/35 bg-white/[0.045] text-stone-300",
    dot: "bg-stone-400",
    rail: "border-l-stone-500",
    block: "border-stone-500/25 bg-white/[0.045]",
  },
};

const eventTypeClasses: Record<string, string> = {
  hard: "border-coral/30 bg-coral/10 text-coral",
  flexible: "border-moss/30 bg-moss/10 text-moss",
  informational: "border-gold/30 bg-gold/10 text-gold",
};

const dayHours = Array.from({ length: 17 }, (_, index) => index + 6);

function startOfDay(date: Date) {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
}

function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function startOfWeek(date: Date) {
  const day = startOfDay(date);
  const weekday = day.getDay();
  day.setDate(day.getDate() - weekday);
  return day;
}

function sameDay(first: Date, second: Date) {
  return first.toDateString() === second.toDateString();
}

function eventStart(event: CalendarEvent) {
  return new Date(event.start);
}

function eventEnd(event: CalendarEvent) {
  return new Date(event.end);
}

function eventRange(event: CalendarEvent) {
  if (event.all_day) {
    return "All day";
  }
  return `${formatTime(event.start)} - ${formatTime(event.end)}`;
}

function eventCategory(event: CalendarEvent) {
  const category = event.event_category || event.event_type || "flexible";
  if (category === "soft") {
    return "informational";
  }
  if (category === "unknown") {
    return "flexible";
  }
  return category;
}

function inferProject(event: CalendarEvent): ProjectLabel {
  const text = `${event.title} ${event.location ?? ""}`.toLowerCase();
  const prefixed = event.title.match(/^(.+?)\s+[—-]\s+/)?.[1]?.trim();
  if (prefixed && projectLabels.includes(prefixed as ProjectLabel)) {
    return prefixed as ProjectLabel;
  }
  if (text.includes("a&m") || text.includes("tamu") || text.includes("blinn") || text.includes("nikhil") || text.includes("andy") || text.includes("kamden")) {
    return "A&M";
  }
  if (text.includes("xo") || text.includes("ashwin") || text.includes("charlie") || text.includes("vr") || text.includes("headset")) {
    return "XO";
  }
  if (text.includes("nebulo") || text.includes("brandon") || text.includes("context control")) {
    return "Nebulo";
  }
  if (text.includes("client") || text.includes("freelance") || text.includes("law firm") || text.includes("dentist") || text.includes("realtor") || text.includes("website")) {
    return "Freelance";
  }
  if (text.includes("gym") || text.includes("personal") || text.includes("target") || text.includes("sam") || text.includes("jai") || text.includes("krrish") || text.includes("carrollton") || text.includes("utd")) {
    return "Personal";
  }
  return "Misc";
}

function shortDate(date: Date) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

function fullDate(date: Date) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(date);
}

function monthTitle(date: Date) {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  }).format(date);
}

function minutesFromDayStart(event: CalendarEvent) {
  if (event.all_day) {
    return 6 * 60;
  }
  const start = eventStart(event);
  return start.getHours() * 60 + start.getMinutes();
}

function eventDuration(event: CalendarEvent) {
  if (event.all_day) {
    return 60;
  }
  return Math.max(30, event.duration_minutes || Math.round((eventEnd(event).getTime() - eventStart(event).getTime()) / 60000));
}

function EventCard({ event, compact = false }: { event: CalendarEvent; compact?: boolean }) {
  const project = inferProject(event);
  const style = projectStyles[project];
  const category = eventCategory(event);

  return (
    <article className={`min-w-0 rounded-lg border border-l-4 p-3 shadow-card ${style.rail} ${style.block}`}>
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className={`${compact ? "text-sm" : "text-base"} break-words font-semibold text-pearl`}>
            {event.title}
          </h4>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-stone-400">
            <Clock3 className="h-3.5 w-3.5 shrink-0 text-stone-500" aria-hidden="true" />
            {eventRange(event)}
          </p>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-1 text-[0.68rem] font-medium ${style.chip}`}>
          {project}
        </span>
      </div>

      {!compact ? (
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-stone-500">
          <span className={`rounded-full border px-2 py-1 ${eventTypeClasses[category] ?? eventTypeClasses.flexible}`}>
            {category}
          </span>
          <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
            {event.busy ? "busy" : "free"}
          </span>
          <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
            {event.duration_minutes} min
          </span>
          {event.attendees_count ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-black/20 px-2 py-1">
              <Users className="h-3.5 w-3.5" aria-hidden="true" />
              {event.attendees_count}
            </span>
          ) : null}
          {event.location ? (
            <span className="inline-flex min-w-0 items-center gap-1 rounded-full border border-white/10 bg-black/20 px-2 py-1">
              <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{event.location}</span>
            </span>
          ) : null}
          {event.html_link ? (
            <a
              href={event.html_link}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-black/20 px-2 py-1 text-stone-300 hover:border-moss/40 hover:text-moss"
            >
              Open
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
      {label}
    </div>
  );
}

export default function CalendarPage() {
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [view, setView] = useState<CalendarView>("week");
  const [anchorDate, setAnchorDate] = useState(() => startOfDay(new Date()));
  const [selectedProjects, setSelectedProjects] = useState<Set<ProjectLabel>>(() => new Set(projectLabels));
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const sortedEvents = useMemo(
    () => [...(data?.events ?? [])].sort((first, second) => eventStart(first).getTime() - eventStart(second).getTime()),
    [data],
  );

  const filteredEvents = useMemo(
    () => sortedEvents.filter((event) => selectedProjects.has(inferProject(event))),
    [selectedProjects, sortedEvents],
  );

  const dayEvents = useMemo(
    () => filteredEvents.filter((event) => sameDay(eventStart(event), anchorDate)),
    [anchorDate, filteredEvents],
  );

  const weekDays = useMemo(() => {
    const start = startOfWeek(anchorDate);
    return Array.from({ length: 7 }, (_, index) => addDays(start, index));
  }, [anchorDate]);

  const weekEventsByDay = useMemo(
    () =>
      weekDays.map((day) => ({
        day,
        events: filteredEvents.filter((event) => sameDay(eventStart(event), day)),
      })),
    [filteredEvents, weekDays],
  );

  const upcomingGroups = useMemo(() => {
    const groups = new Map<string, CalendarEvent[]>();
    for (const event of filteredEvents) {
      const key = eventStart(event).toDateString();
      const group = groups.get(key) ?? [];
      group.push(event);
      groups.set(key, group);
    }
    return Array.from(groups.entries()).map(([key, events]) => ({
      date: new Date(key),
      events,
    }));
  }, [filteredEvents]);

  const totalVisible = filteredEvents.length;
  const activeFilterCount = selectedProjects.size;

  async function loadCalendar() {
    setIsLoading(true);
    setError(null);
    try {
      setData(await apiRequest<CalendarResponse>("/calendar?days=14"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load calendar.");
    } finally {
      setIsLoading(false);
    }
  }

  function shiftDate(direction: -1 | 1) {
    setAnchorDate((current) => addDays(current, view === "day" ? direction : direction * 7));
  }

  function toggleProject(project: ProjectLabel) {
    setSelectedProjects((current) => {
      const next = new Set(current);
      if (next.has(project)) {
        next.delete(project);
      } else {
        next.add(project);
      }
      return next;
    });
  }

  useEffect(() => {
    void loadCalendar();
  }, []);

  return (
    <section className="mx-auto w-[calc(100vw-2rem)] max-w-7xl space-y-5 pb-6 sm:w-full">
      <div className="flex flex-col gap-4 rounded-lg border border-line bg-panel/80 p-4 shadow-card md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-coral">Google Calendar</p>
          <h3 className="mt-2 text-3xl font-semibold text-pearl md:text-4xl">
            {view === "day" ? fullDate(anchorDate) : view === "week" ? monthTitle(anchorDate) : "Upcoming"}
          </h3>
          <p className="mt-2 text-sm text-stone-400">
            {isLoading ? "Syncing calendar..." : `${totalVisible} events shown from real Google Calendar data`}
          </p>
          {error ? <p className="mt-2 text-sm text-coral">{error}</p> : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-line bg-black/20 p-1">
            {(["day", "week", "upcoming"] as CalendarView[]).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setView(item)}
                className={`h-9 rounded-md px-3 text-sm font-medium capitalize transition ${
                  view === item ? "bg-white text-ink" : "text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
                }`}
              >
                {item}
              </button>
            ))}
          </div>

          {view !== "upcoming" ? (
            <div className="inline-flex rounded-lg border border-line bg-black/20">
              <button
                type="button"
                onClick={() => shiftDate(-1)}
                aria-label="Previous"
                className="inline-flex h-10 w-10 items-center justify-center text-stone-400 hover:text-pearl"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => setAnchorDate(startOfDay(new Date()))}
                className="h-10 border-x border-line px-3 text-sm font-medium text-stone-300 hover:text-pearl"
              >
                Today
              </button>
              <button
                type="button"
                onClick={() => shiftDate(1)}
                aria-label="Next"
                className="inline-flex h-10 w-10 items-center justify-center text-stone-400 hover:text-pearl"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          ) : null}

          <button
            type="button"
            onClick={() => void loadCalendar()}
            aria-label="Refresh calendar"
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </div>
      </div>

      {data?.errors.length ? (
        <div className="rounded-lg border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Calendar read issue
          </div>
          <p className="mt-2 leading-6">{data.errors.join(" ")}</p>
        </div>
      ) : null}

      <div className="flex gap-2 overflow-x-auto rounded-lg border border-line bg-white/[0.035] p-2">
        {projectLabels.map((project) => {
          const selected = selectedProjects.has(project);
          return (
            <button
              key={project}
              type="button"
              onClick={() => toggleProject(project)}
              className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-md border px-3 text-xs font-medium transition ${
                selected ? projectStyles[project].chip : "border-white/10 bg-black/20 text-stone-500"
              }`}
            >
              <span className={`h-2.5 w-2.5 rounded-full ${selected ? projectStyles[project].dot : "bg-stone-700"}`} />
              {project}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() =>
            setSelectedProjects((current) =>
              current.size === projectLabels.length ? new Set<ProjectLabel>() : new Set(projectLabels),
            )
          }
          className="ml-auto inline-flex h-9 shrink-0 items-center rounded-md border border-white/10 bg-black/20 px-3 text-xs font-medium text-stone-300 hover:text-pearl"
        >
          {activeFilterCount === projectLabels.length ? "Clear" : "All"}
        </button>
      </div>

      {isLoading && !data ? <EmptyState label="Loading calendar" /> : null}

      {!isLoading || data ? (
        <>
          {view === "day" ? (
            <section className="grid gap-4 lg:grid-cols-[5.5rem_minmax(0,1fr)]">
              <div className="hidden rounded-lg border border-line bg-white/[0.035] p-3 text-xs text-stone-500 lg:block">
                {dayHours.map((hour) => (
                  <div key={hour} className="h-16">
                    {new Intl.DateTimeFormat(undefined, { hour: "numeric" }).format(new Date(2026, 0, 1, hour))}
                  </div>
                ))}
              </div>
              <div className="min-h-[32rem] rounded-lg border border-line bg-white/[0.035] p-3">
                {dayEvents.length === 0 ? (
                  <EmptyState label="No events on this day for the selected projects." />
                ) : (
                  <div className="space-y-3 lg:relative lg:h-[68rem] lg:space-y-0">
                    {dayEvents.map((event) => {
                      const top = Math.max(0, ((minutesFromDayStart(event) - 6 * 60) / 60) * 4);
                      const height = Math.max(3, (eventDuration(event) / 60) * 4);
                      return (
                        <div
                          key={event.id ?? `${event.title}:${event.start}`}
                          className="lg:absolute lg:left-0 lg:right-0 lg:px-2"
                          style={{ top: `${top}rem`, minHeight: `${height}rem` }}
                        >
                          <EventCard event={event} />
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </section>
          ) : null}

          {view === "week" ? (
            <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
              {weekEventsByDay.map(({ day, events }) => (
                <div
                  key={day.toISOString()}
                  className={`min-w-0 rounded-lg border p-3 ${
                    sameDay(day, new Date()) ? "border-moss/35 bg-moss/10" : "border-line bg-white/[0.035]"
                  }`}
                >
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div>
                      <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500">
                        {new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(day)}
                      </p>
                      <h4 className="mt-1 text-lg font-semibold text-pearl">{day.getDate()}</h4>
                    </div>
                    <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1 text-xs text-stone-400">
                      {events.length}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {events.length ? (
                      events.map((event) => <EventCard key={event.id ?? `${event.title}:${event.start}`} event={event} compact />)
                    ) : (
                      <p className="rounded-lg border border-white/10 bg-black/20 p-3 text-xs text-stone-500">Open</p>
                    )}
                  </div>
                </div>
              ))}
            </section>
          ) : null}

          {view === "upcoming" ? (
            <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
              <div className="space-y-5">
                {upcomingGroups.length ? (
                  upcomingGroups.map(({ date, events }) => (
                    <section key={date.toISOString()} className="min-w-0">
                      <h3 className="mb-3 text-xs font-medium uppercase tracking-[0.24em] text-stone-500">
                        {shortDate(date)}
                      </h3>
                      <div className="space-y-3">
                        {events.map((event) => (
                          <EventCard key={event.id ?? `${event.title}:${event.start}`} event={event} />
                        ))}
                      </div>
                    </section>
                  ))
                ) : (
                  <EmptyState label="No upcoming events for the selected projects." />
                )}
              </div>

              <aside className="space-y-4">
                <div className="glass-panel rounded-lg p-5">
                  <h3 className="text-xl font-semibold text-pearl">Conflicts</h3>
                  <div className="mt-4 space-y-3">
                    {data?.conflicts.length ? (
                      data.conflicts.map((conflict) => (
                        <article key={`${conflict.first_event_id}:${conflict.second_event_id}:${conflict.start}`} className="rounded-lg border border-coral/25 bg-coral/10 p-4">
                          <p className="text-sm font-medium text-coral">
                            {conflict.first_event_title} overlaps {conflict.second_event_title}
                          </p>
                          <p className="mt-2 text-sm text-stone-300">
                            {formatDateTime(conflict.start)} - {formatTime(conflict.end)}
                          </p>
                        </article>
                      ))
                    ) : (
                      <div className="rounded-lg bg-black/20 p-4 text-sm text-stone-500">No conflicts detected.</div>
                    )}
                  </div>
                </div>

                <div className="glass-panel rounded-lg p-5">
                  <h3 className="text-xl font-semibold text-pearl">Project Labels</h3>
                  <div className="mt-4 space-y-2">
                    {projectLabels.map((project) => (
                      <div key={project} className="flex items-center justify-between rounded-lg bg-black/20 px-3 py-2">
                        <span className="text-sm text-stone-300">{project}</span>
                        <span className={`h-3 w-3 rounded-full ${projectStyles[project].dot}`} />
                      </div>
                    ))}
                  </div>
                </div>
              </aside>
            </section>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
