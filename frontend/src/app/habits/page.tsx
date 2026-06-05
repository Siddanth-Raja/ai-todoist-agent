"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Check, Circle, Minus, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import {
  apiRequest,
  formatDateTime,
  type HabitCheckIn,
  type HabitDefinition,
  type HabitStatus,
} from "@/lib/api";

type HabitForm = {
  name: string;
  description: string;
  enabled: boolean;
};

const emptyForm: HabitForm = {
  name: "",
  description: "",
  enabled: true,
};

const statusConfig: Record<
  HabitStatus,
  {
    label: string;
    icon: typeof Check;
    className: string;
  }
> = {
  yes: {
    label: "Yes",
    icon: Check,
    className: "border-moss/30 bg-moss/10 text-moss hover:bg-moss/15",
  },
  partial: {
    label: "Partial",
    icon: Minus,
    className: "border-gold/30 bg-gold/10 text-gold hover:bg-gold/15",
  },
  no: {
    label: "No",
    icon: X,
    className: "border-coral/30 bg-coral/10 text-coral hover:bg-coral/15",
  },
};

function statusLabel(status: HabitStatus) {
  return statusConfig[status].label;
}

export default function HabitsPage() {
  const [habits, setHabits] = useState<HabitDefinition[]>([]);
  const [checkins, setCheckins] = useState<HabitCheckIn[]>([]);
  const [form, setForm] = useState<HabitForm>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loggingHabit, setLoggingHabit] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const enabledHabits = useMemo(() => habits.filter((habit) => habit.enabled), [habits]);

  async function loadHabits() {
    setIsLoading(true);
    setError(null);
    try {
      const [habitRows, checkinRows] = await Promise.all([
        apiRequest<HabitDefinition[]>("/habits"),
        apiRequest<HabitCheckIn[]>("/habit-checkins?limit=20"),
      ]);
      setHabits(habitRows);
      setCheckins(checkinRows);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load habits.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadHabits();
  }, []);

  function resetForm() {
    setForm(emptyForm);
    setEditingId(null);
  }

  function editHabit(habit: HabitDefinition) {
    setForm({
      name: habit.name,
      description: habit.description,
      enabled: habit.enabled,
    });
    setEditingId(habit.id);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      const path = editingId ? `/habits/${editingId}` : "/habits";
      const method = editingId ? "PATCH" : "POST";
      await apiRequest<HabitDefinition>(path, {
        method,
        body: JSON.stringify(form),
      });
      resetForm();
      await loadHabits();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save habit.");
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteHabit(habit: HabitDefinition) {
    setError(null);
    try {
      await apiRequest<{ deleted: boolean }>(`/habits/${habit.id}`, { method: "DELETE" });
      setHabits((current) => current.filter((item) => item.id !== habit.id));
      if (editingId === habit.id) {
        resetForm();
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete habit.");
    }
  }

  async function logCheckIn(habit: HabitDefinition, status: HabitStatus) {
    setLoggingHabit(`${habit.id}:${status}`);
    setError(null);
    try {
      await apiRequest<HabitCheckIn>("/habit-checkins", {
        method: "POST",
        body: JSON.stringify({
          habit: habit.id,
          status,
          timestamp: new Date().toISOString(),
        }),
      });
      await loadHabits();
    } catch (logError) {
      setError(logError instanceof Error ? logError.message : "Unable to log habit.");
    } finally {
      setLoggingHabit(null);
    }
  }

  return (
    <section className="mx-auto grid w-[calc(100vw-2rem)] max-w-6xl gap-5 pb-6 sm:w-full xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.24em] text-moss">Check-ins</p>
            <h3 className="mt-2 text-3xl font-semibold text-pearl">Gym, running, work</h3>
            {error ? <p className="mt-2 text-sm text-coral">{error}</p> : null}
          </div>
          <button
            type="button"
            onClick={() => void loadHabits()}
            aria-label="Refresh habits"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {enabledHabits.map((habit) => (
            <article key={habit.id} className="rounded-lg border border-white/10 bg-white/[0.055] p-4 shadow-card">
              <div className="mb-6 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="break-words text-xl font-semibold text-pearl">{habit.name}</h4>
                  <p className="mt-2 min-h-10 text-sm leading-5 text-stone-500">{habit.description}</p>
                </div>
                <Circle className="mt-1 h-5 w-5 shrink-0 text-moss" aria-hidden="true" />
              </div>
              <div className="grid grid-cols-3 gap-2">
                {(Object.keys(statusConfig) as HabitStatus[]).map((status) => {
                  const Icon = statusConfig[status].icon;
                  const isLogging = loggingHabit === `${habit.id}:${status}`;
                  return (
                    <button
                      key={status}
                      type="button"
                      onClick={() => void logCheckIn(habit, status)}
                      disabled={Boolean(loggingHabit)}
                      className={`inline-flex min-h-11 items-center justify-center gap-1 rounded-lg border px-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${statusConfig[status].className}`}
                    >
                      <Icon className={`h-4 w-4 ${isLogging ? "animate-pulse" : ""}`} aria-hidden="true" />
                      {statusConfig[status].label}
                    </button>
                  );
                })}
              </div>
            </article>
          ))}
        </div>

        <div className="glass-panel rounded-lg p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-xl font-semibold text-pearl">Recent logs</h3>
            <span className="text-sm text-stone-500">{checkins.length}</span>
          </div>
          {checkins.length === 0 ? (
            <div className="rounded-lg border border-line bg-white/[0.04] p-4 text-sm text-stone-400">
              No check-ins yet.
            </div>
          ) : (
            <div className="space-y-2">
              {checkins.map((checkin) => (
                <article key={checkin.id} className="flex items-center justify-between gap-4 rounded-lg bg-black/20 p-3">
                  <div className="min-w-0">
                    <p className="font-medium text-pearl">{checkin.habit}</p>
                    <p className="mt-1 text-sm text-stone-500">{formatDateTime(checkin.timestamp)}</p>
                    {checkin.note ? <p className="mt-1 text-sm text-stone-400">{checkin.note}</p> : null}
                  </div>
                  <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1 text-xs text-stone-300">
                    {statusLabel(checkin.status)}
                  </span>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>

      <aside className="space-y-4">
        <form onSubmit={handleSubmit} className="glass-panel rounded-lg p-5">
          <div className="mb-5 flex items-center justify-between gap-3">
            <h3 className="text-xl font-semibold text-pearl">{editingId ? "Edit habit" : "Add habit"}</h3>
            {editingId ? (
              <button
                type="button"
                onClick={resetForm}
                aria-label="Cancel edit"
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            ) : null}
          </div>
          <label className="block">
            <span className="text-sm font-medium text-stone-300">Name</span>
            <input
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              className="mt-2 min-h-12 w-full rounded-lg border border-line bg-white/[0.04] px-3 text-sm text-pearl outline-none focus:border-moss/70"
              required
            />
          </label>
          <label className="mt-4 block">
            <span className="text-sm font-medium text-stone-300">Description</span>
            <textarea
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              className="mt-2 min-h-24 w-full resize-y rounded-lg border border-line bg-white/[0.04] px-3 py-3 text-sm leading-6 text-pearl outline-none focus:border-moss/70"
            />
          </label>
          <label className="mt-4 flex min-h-12 items-center gap-3 rounded-lg border border-line bg-white/[0.04] px-3 text-sm text-stone-300">
            <input
              checked={form.enabled}
              onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))}
              type="checkbox"
              className="h-4 w-4 accent-moss"
            />
            Enabled
          </label>
          <button
            type="submit"
            disabled={isSaving}
            className="mt-5 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-lg bg-moss px-4 text-sm font-semibold text-ink transition hover:bg-[#b7e5c9] disabled:cursor-not-allowed disabled:bg-stone-700 disabled:text-stone-500"
          >
            {editingId ? <Check className="h-4 w-4" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
            {editingId ? "Save" : "Add"}
          </button>
        </form>

        <div className="glass-panel rounded-lg p-5">
          <h3 className="mb-4 text-xl font-semibold text-pearl">Definitions</h3>
          <div className="space-y-2">
            {habits.map((habit) => (
              <article key={habit.id} className={`rounded-lg bg-black/20 p-3 ${habit.enabled ? "" : "opacity-55"}`}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-pearl">{habit.name}</p>
                    <p className="mt-1 truncate text-sm text-stone-500">{habit.enabled ? "enabled" : "disabled"}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      onClick={() => editHabit(habit)}
                      aria-label="Edit habit"
                      className="flex h-9 w-9 items-center justify-center rounded-lg text-stone-400 hover:bg-white/[0.07] hover:text-pearl"
                    >
                      <Pencil className="h-4 w-4" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      onClick={() => void deleteHabit(habit)}
                      aria-label="Delete habit"
                      className="flex h-9 w-9 items-center justify-center rounded-lg text-stone-400 hover:bg-coral/10 hover:text-coral"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </aside>
    </section>
  );
}
