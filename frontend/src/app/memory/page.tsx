"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  Lightbulb,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Trash2,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { apiRequest, type MemoryEntry } from "@/lib/api";

type MemoryGroupKey =
  | "projects"
  | "people"
  | "groups"
  | "rules"
  | "preferences"
  | "patterns"
  | "sensitive_habits";

type MemoryForm = {
  type: string;
  title: string;
  content: string;
  confidence: number;
  enabled: boolean;
};

type MemoryGroup = {
  key: MemoryGroupKey;
  title: string;
  description: string;
  empty: string;
  icon: LucideIcon;
  types: string[];
};

const memoryGroups: MemoryGroup[] = [
  {
    key: "projects",
    title: "Projects",
    description: "Durable context for active work streams and commitments.",
    empty: "Add project context so the assistant can route work to the right life area.",
    icon: BookOpen,
    types: ["project"],
  },
  {
    key: "people",
    title: "People",
    description: "Names, collaborators, and who belongs to what.",
    empty: "Add people memories when a name should carry project or relationship context.",
    icon: Users,
    types: ["person"],
  },
  {
    key: "groups",
    title: "Groups",
    description: "Friend, team, roommate, and collaborator clusters.",
    empty: "Add groups to help classify messages that mention several people at once.",
    icon: Users,
    types: ["group"],
  },
  {
    key: "rules",
    title: "Rules",
    description: "Classification and routing rules the assistant should trust.",
    empty: "Add rules for recurring routing decisions like school, clients, or errands.",
    icon: Lightbulb,
    types: ["rule", "classification_rule"],
  },
  {
    key: "preferences",
    title: "Preferences",
    description: "How you like planning, tone, and decisions handled.",
    empty: "Add preferences for style, defaults, and planning behavior.",
    icon: Sparkles,
    types: ["preference"],
  },
  {
    key: "patterns",
    title: "Patterns",
    description: "Recurring behaviors, rhythms, and observations.",
    empty: "Add patterns when something repeats often enough to guide future planning.",
    icon: RefreshCw,
    types: ["pattern", "routine", "goal"],
  },
  {
    key: "sensitive_habits",
    title: "Sensitive Habits",
    description: "Private habits or context that should be handled carefully.",
    empty: "Add sensitive habits only when they should influence support or planning.",
    icon: ShieldAlert,
    types: ["sensitive_habit", "sensitive_private_habit"],
  },
];

const formTypes = [
  { value: "project", label: "Project" },
  { value: "person", label: "Person" },
  { value: "group", label: "Group" },
  { value: "classification_rule", label: "Rule" },
  { value: "preference", label: "Preference" },
  { value: "pattern", label: "Pattern" },
  { value: "sensitive_habit", label: "Sensitive Habit" },
];

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

function groupForEntry(entry: MemoryEntry): MemoryGroupKey {
  const type = entry.type.toLowerCase();
  return memoryGroups.find((group) => group.types.includes(type))?.key ?? "patterns";
}

function confidenceTone(confidence: number) {
  if (confidence >= 0.8) {
    return "border-moss/35 bg-moss/10 text-moss";
  }
  if (confidence >= 0.5) {
    return "border-gold/35 bg-gold/10 text-gold";
  }
  return "border-stone-500/35 bg-white/[0.05] text-stone-300";
}

export default function MemoryPage() {
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [form, setForm] = useState<MemoryForm>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const groupedEntries = useMemo(() => {
    const grouped = new Map<MemoryGroupKey, MemoryEntry[]>();
    for (const group of memoryGroups) {
      grouped.set(group.key, []);
    }
    for (const entry of entries) {
      grouped.get(groupForEntry(entry))?.push(entry);
    }
    return memoryGroups.map((group) => ({
      ...group,
      entries: (grouped.get(group.key) ?? []).sort((first, second) =>
        first.title.localeCompare(second.title),
      ),
    }));
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

  function openAddForm(type = "project") {
    setForm({ ...emptyForm, type });
    setEditingId(null);
    setIsEditorOpen(true);
  }

  function closeEditor() {
    setForm(emptyForm);
    setEditingId(null);
    setIsEditorOpen(false);
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
    setIsEditorOpen(true);
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
      closeEditor();
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
        closeEditor();
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete memory.");
    }
  }

  const enabledCount = entries.filter((entry) => entry.enabled).length;
  const disabledCount = entries.length - enabledCount;

  return (
    <section className="mx-auto w-[calc(100vw-2rem)] max-w-7xl space-y-5 pb-6 sm:w-full">
      <div className="flex flex-col gap-4 rounded-lg border border-line bg-panel/80 p-4 shadow-card lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-moss">Memory Center</p>
          <h3 className="mt-2 text-3xl font-semibold text-pearl md:text-4xl">Assistant context</h3>
          <p className="mt-2 text-sm text-stone-400">
            {isLoading
              ? "Loading saved memory..."
              : `${entries.length} memories, ${enabledCount} enabled, ${disabledCount} disabled`}
          </p>
          {error ? <p className="mt-2 text-sm text-coral">{error}</p> : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => openAddForm()}
            className="inline-flex h-10 items-center gap-2 rounded-lg bg-moss px-4 text-sm font-semibold text-ink transition hover:bg-[#b7e5c9]"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Add Memory
          </button>
          <button
            type="button"
            onClick={() => void loadEntries()}
            aria-label="Refresh memory"
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </div>
      </div>

      {isEditorOpen ? (
        <form onSubmit={handleSubmit} className="rounded-lg border border-moss/25 bg-moss/[0.06] p-4 shadow-card">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-moss">
                {editingId ? "Edit Memory" : "New Memory"}
              </p>
              <h3 className="mt-1 text-xl font-semibold text-pearl">
                {editingId ? "Refine saved context" : "Add context for future decisions"}
              </h3>
            </div>
            <button
              type="button"
              onClick={closeEditor}
              aria-label="Close memory editor"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
            <label className="block">
              <span className="text-sm font-medium text-stone-300">Type</span>
              <select
                value={form.type}
                onChange={(event) => setForm((current) => ({ ...current, type: event.target.value }))}
                className="mt-2 min-h-11 w-full rounded-lg border border-line bg-panel px-3 text-sm text-pearl outline-none focus:border-moss/70"
              >
                {formTypes.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-stone-300">Title</span>
              <input
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                className="mt-2 min-h-11 w-full rounded-lg border border-line bg-white/[0.04] px-3 text-sm text-pearl outline-none focus:border-moss/70"
                required
              />
            </label>
          </div>

          <label className="mt-4 block">
            <span className="text-sm font-medium text-stone-300">Content</span>
            <textarea
              value={form.content}
              onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))}
              className="mt-2 min-h-28 w-full resize-y rounded-lg border border-line bg-white/[0.04] px-3 py-3 text-sm leading-6 text-pearl outline-none focus:border-moss/70"
              required
            />
          </label>

          <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_180px] md:items-end">
            <label className="block">
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

            <label className="flex min-h-11 items-center gap-3 rounded-lg border border-line bg-white/[0.04] px-3 text-sm text-stone-300">
              <input
                checked={form.enabled}
                onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))}
                type="checkbox"
                className="h-4 w-4 accent-moss"
              />
              Enabled
            </label>
          </div>

          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={closeEditor}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-4 text-sm font-medium text-stone-300 transition hover:text-pearl"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-moss px-4 text-sm font-semibold text-ink transition hover:bg-[#b7e5c9] disabled:cursor-not-allowed disabled:bg-stone-700 disabled:text-stone-500"
            >
              {editingId ? <Check className="h-4 w-4" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
              {editingId ? "Save" : "Add"}
            </button>
          </div>
        </form>
      ) : null}

      {isLoading ? (
        <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
          Loading memory
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {groupedEntries.map((group) => {
            const Icon = group.icon;
            return (
              <section key={group.key} className="min-w-0 rounded-lg border border-line bg-white/[0.035] p-4 shadow-card">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-black/20 text-moss">
                        <Icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <div>
                        <h3 className="text-xl font-semibold text-pearl">{group.title}</h3>
                        <p className="text-xs text-stone-500">{group.entries.length} memories</p>
                      </div>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-stone-400">{group.description}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openAddForm(group.types[0])}
                    aria-label={`Add ${group.title} memory`}
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
                  >
                    <Plus className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>

                {group.entries.length === 0 ? (
                  <div className="rounded-lg border border-white/10 bg-black/20 p-4 text-sm leading-6 text-stone-500">
                    {group.empty}
                  </div>
                ) : (
                  <div className="grid gap-3">
                    {group.entries.map((entry) => (
                      <article
                        key={entry.id}
                        className={`rounded-lg border border-l-4 border-white/10 bg-black/20 p-4 ${
                          entry.enabled ? "border-l-moss" : "border-l-stone-600 opacity-60"
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
                          <span className="rounded-full border border-white/10 bg-white/[0.05] px-2 py-1 capitalize">
                            {formatType(entry.type)}
                          </span>
                          <span className={`rounded-full border px-2 py-1 ${confidenceTone(entry.confidence)}`}>
                            {Math.round(entry.confidence * 100)}% confidence
                          </span>
                          <span className="rounded-full border border-white/10 bg-white/[0.05] px-2 py-1">
                            {entry.enabled ? "enabled" : "disabled"}
                          </span>
                          {entry.source ? (
                            <span className="rounded-full border border-white/10 bg-white/[0.05] px-2 py-1">
                              {entry.source}
                            </span>
                          ) : null}
                          <span className="rounded-full border border-white/10 bg-white/[0.05] px-2 py-1">
                            Updated {formatDate(entry.updated_at)}
                          </span>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {error ? (
        <div className="rounded-lg border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Memory issue
          </div>
          <p className="mt-2 leading-6">{error}</p>
        </div>
      ) : null}
    </section>
  );
}
