"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Check, Pencil, Plus, Power, RefreshCw, Trash2, X } from "lucide-react";
import { apiRequest, type MemoryEntry } from "@/lib/api";

const memoryTypes = [
  "project",
  "person",
  "group",
  "preference",
  "classification_rule",
  "routine",
  "goal",
  "pattern",
  "sensitive_private_habit",
];

type MemoryForm = {
  type: string;
  title: string;
  content: string;
  confidence: number;
  enabled: boolean;
};

const emptyForm: MemoryForm = {
  type: "project",
  title: "",
  content: "",
  confidence: 0.6,
  enabled: true,
};

function formatType(value: string) {
  return value.replaceAll("_", " ");
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function MemoryPage() {
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [form, setForm] = useState<MemoryForm>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const groupedEntries = useMemo(() => {
    const grouped = new Map<string, MemoryEntry[]>();
    for (const entry of entries) {
      const group = grouped.get(entry.type) ?? [];
      group.push(entry);
      grouped.set(entry.type, group);
    }
    return Array.from(grouped.entries()).sort(([first], [second]) => first.localeCompare(second));
  }, [entries]);

  async function loadEntries() {
    setIsLoading(true);
    setError(null);
    try {
      setEntries(await apiRequest<MemoryEntry[]>("/memory"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load memory.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadEntries();
  }, []);

  function resetForm() {
    setForm(emptyForm);
    setEditingId(null);
  }

  function editEntry(entry: MemoryEntry) {
    setForm({
      type: entry.type,
      title: entry.title,
      content: entry.content,
      confidence: entry.confidence,
      enabled: entry.enabled,
    });
    setEditingId(entry.id);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      const path = editingId ? `/memory/${editingId}` : "/memory";
      const method = editingId ? "PATCH" : "POST";
      await apiRequest<MemoryEntry>(path, {
        method,
        body: JSON.stringify(form),
      });
      resetForm();
      await loadEntries();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save memory.");
    } finally {
      setIsSaving(false);
    }
  }

  async function toggleEntry(entry: MemoryEntry) {
    setError(null);
    try {
      const updated = await apiRequest<MemoryEntry>(`/memory/${entry.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !entry.enabled }),
      });
      setEntries((current) => current.map((item) => (item.id === entry.id ? updated : item)));
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : "Unable to update memory.");
    }
  }

  async function deleteEntry(entry: MemoryEntry) {
    setError(null);
    try {
      await apiRequest<{ deleted: boolean }>(`/memory/${entry.id}`, { method: "DELETE" });
      setEntries((current) => current.filter((item) => item.id !== entry.id));
      if (editingId === entry.id) {
        resetForm();
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete memory.");
    }
  }

  return (
    <section className="mx-auto grid w-[calc(100vw-2rem)] max-w-6xl gap-5 pb-6 sm:w-full xl:grid-cols-[360px_minmax(0,1fr)]">
      <form onSubmit={handleSubmit} className="glass-panel h-fit rounded-lg p-5">
        <div className="mb-5 flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.24em] text-moss">Memory</p>
            <h3 className="mt-2 text-2xl font-semibold text-pearl">
              {editingId ? "Edit entry" : "Add entry"}
            </h3>
          </div>
          {editingId ? (
            <button
              type="button"
              onClick={resetForm}
              aria-label="Cancel edit"
              className="flex h-10 w-10 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
        </div>

        <label className="block">
          <span className="text-sm font-medium text-stone-300">Type</span>
          <select
            value={form.type}
            onChange={(event) => setForm((current) => ({ ...current, type: event.target.value }))}
            className="mt-2 min-h-12 w-full rounded-lg border border-line bg-panel px-3 text-sm text-pearl outline-none focus:border-moss/70"
          >
            {memoryTypes.map((type) => (
              <option key={type} value={type}>
                {formatType(type)}
              </option>
            ))}
          </select>
        </label>

        <label className="mt-4 block">
          <span className="text-sm font-medium text-stone-300">Title</span>
          <input
            value={form.title}
            onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
            className="mt-2 min-h-12 w-full rounded-lg border border-line bg-white/[0.04] px-3 text-sm text-pearl outline-none focus:border-moss/70"
            required
          />
        </label>

        <label className="mt-4 block">
          <span className="text-sm font-medium text-stone-300">Content</span>
          <textarea
            value={form.content}
            onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))}
            className="mt-2 min-h-36 w-full resize-y rounded-lg border border-line bg-white/[0.04] px-3 py-3 text-sm leading-6 text-pearl outline-none focus:border-moss/70"
            required
          />
        </label>

        <label className="mt-4 block">
          <span className="flex items-center justify-between text-sm font-medium text-stone-300">
            Confidence
            <span className="text-stone-500">{Math.round(form.confidence * 100)}%</span>
          </span>
          <input
            value={form.confidence}
            onChange={(event) =>
              setForm((current) => ({ ...current, confidence: Number(event.target.value) }))
            }
            min={0}
            max={1}
            step={0.05}
            type="range"
            className="mt-3 w-full accent-moss"
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

      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm text-stone-500">{entries.length} entries</p>
            {error ? <p className="mt-1 text-sm text-coral">{error}</p> : null}
          </div>
          <button
            type="button"
            onClick={() => void loadEntries()}
            aria-label="Refresh memory"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </div>

        {isLoading ? (
          <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
            Loading memory
          </div>
        ) : groupedEntries.length === 0 ? (
          <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
            No memory entries yet.
          </div>
        ) : (
          groupedEntries.map(([type, group]) => (
            <section key={type} className="min-w-0">
              <h3 className="mb-3 text-xs font-medium uppercase tracking-[0.24em] text-stone-500">
                {formatType(type)}
              </h3>
              <div className="grid gap-3">
                {group.map((entry) => (
                  <article
                    key={entry.id}
                    className={`rounded-lg border border-white/10 bg-white/[0.055] p-4 shadow-card ${
                      entry.enabled ? "" : "opacity-55"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <h4 className="break-words text-lg font-semibold text-pearl">{entry.title}</h4>
                        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-stone-300">
                          {entry.content}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          onClick={() => editEntry(entry)}
                          aria-label="Edit memory"
                          className="flex h-9 w-9 items-center justify-center rounded-lg text-stone-400 hover:bg-white/[0.07] hover:text-pearl"
                        >
                          <Pencil className="h-4 w-4" aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void toggleEntry(entry)}
                          aria-label={entry.enabled ? "Disable memory" : "Enable memory"}
                          className="flex h-9 w-9 items-center justify-center rounded-lg text-stone-400 hover:bg-white/[0.07] hover:text-pearl"
                        >
                          <Power className="h-4 w-4" aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void deleteEntry(entry)}
                          aria-label="Delete memory"
                          className="flex h-9 w-9 items-center justify-center rounded-lg text-stone-400 hover:bg-coral/10 hover:text-coral"
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                      <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
                        {Math.round(entry.confidence * 100)}%
                      </span>
                      <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
                        {entry.enabled ? "enabled" : "disabled"}
                      </span>
                      <span>Updated {formatDate(entry.updated_at)}</span>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </section>
  );
}
