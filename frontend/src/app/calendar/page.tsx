"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CalendarClock, MapPin, RefreshCw, Users } from "lucide-react";
import {
  apiRequest,
  formatDateTime,
  formatTime,
  type CalendarEvent,
  type CalendarResponse,
} from "@/lib/api";

const labelClasses: Record<string, string> = {
  hard: "border-coral/30 bg-coral/10 text-coral",
  flexible: "border-moss/30 bg-moss/10 text-moss",
  informational: "border-gold/30 bg-gold/10 text-gold",
};

function eventDay(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function eventRange(event: CalendarEvent) {
  if (event.all_day) {
    return "All day";
  }
  return `${formatTime(event.start)}-${formatTime(event.end)}`;
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

export default function CalendarPage() {
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const groupedEvents = useMemo(() => {
    const grouped = new Map<string, CalendarEvent[]>();
    for (const event of data?.events ?? []) {
      const day = eventDay(event.start);
      const group = grouped.get(day) ?? [];
      group.push(event);
      grouped.set(day, group);
    }
    return Array.from(grouped.entries());
  }, [data]);

  async function loadCalendar() {
    setIsLoading(true);
    setError(null);
    try {
      setData(await apiRequest<CalendarResponse>("/calendar?days=7"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load calendar.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadCalendar();
  }, []);

  return (
    <section className="mx-auto grid w-[calc(100vw-2rem)] max-w-6xl gap-5 pb-6 sm:w-full xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.24em] text-coral">Google Calendar</p>
            <h3 className="mt-2 text-3xl font-semibold text-pearl">
              {data?.events.length ?? 0} upcoming events
            </h3>
            {error ? <p className="mt-2 text-sm text-coral">{error}</p> : null}
          </div>
          <button
            type="button"
            onClick={() => void loadCalendar()}
            aria-label="Refresh calendar"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
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

        {isLoading && !data ? (
          <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
            Loading calendar
          </div>
        ) : groupedEvents.length === 0 ? (
          <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
            No upcoming events found.
          </div>
        ) : (
          <div className="space-y-5">
            {groupedEvents.map(([day, events]) => (
              <section key={day} className="min-w-0">
                <h3 className="mb-3 text-xs font-medium uppercase tracking-[0.24em] text-stone-500">
                  {day}
                </h3>
                <div className="space-y-3">
                  {events.map((event) => (
                    <article key={event.id ?? `${event.title}:${event.start}`} className="rounded-lg border border-white/10 bg-white/[0.055] p-4 shadow-card">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h4 className="break-words text-xl font-semibold text-pearl">{event.title}</h4>
                          <p className="mt-2 flex items-center gap-2 text-sm text-stone-400">
                            <CalendarClock className="h-4 w-4 text-moss" aria-hidden="true" />
                            {eventRange(event)}
                          </p>
                        </div>
                        <span className={`rounded-full border px-3 py-1 text-xs font-medium ${labelClasses[eventCategory(event)] ?? labelClasses.flexible}`}>
                          {eventCategory(event)}
                        </span>
                      </div>

                      <div className="mt-4 flex flex-wrap gap-2 text-xs text-stone-500">
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
                          <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-black/20 px-2 py-1">
                            <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
                            {event.location}
                          </span>
                        ) : null}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
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
                    {formatDateTime(conflict.start)}-{formatTime(conflict.end)}
                  </p>
                </article>
              ))
            ) : (
              <div className="rounded-lg bg-black/20 p-4 text-sm text-stone-500">No conflicts detected.</div>
            )}
          </div>
        </div>

        <div className="glass-panel rounded-lg p-5">
          <h3 className="text-xl font-semibold text-pearl">Labels</h3>
          <div className="mt-4 space-y-2">
            {["hard", "flexible", "informational"].map((label) => (
              <div key={label} className="flex items-center justify-between rounded-lg bg-black/20 px-3 py-2">
                <span className="text-sm capitalize text-stone-300">{label}</span>
                <span className={`h-3 w-3 rounded-full border ${labelClasses[label]}`} />
              </div>
            ))}
          </div>
        </div>
      </aside>
    </section>
  );
}
