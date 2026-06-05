"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, ExternalLink, RefreshCw } from "lucide-react";
import { apiRequest, type TaskItem, type TasksResponse } from "@/lib/api";

function formatDue(task: TaskItem) {
  if (task.due_date) {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
    }).format(new Date(`${task.due_date}T12:00:00`));
  }

  const dueDate = task.due?.date;
  if (typeof dueDate === "string") {
    return dueDate;
  }

  return "No due date";
}

function priorityLabel(priority?: number | null) {
  if (!priority) {
    return "P?";
  }
  return `P${priority}`;
}

function dueClass(status?: string | null) {
  if (status === "overdue") {
    return "border-coral/30 bg-coral/10 text-coral";
  }
  if (status === "due_today") {
    return "border-gold/30 bg-gold/10 text-gold";
  }
  return "border-white/10 bg-white/[0.06] text-stone-400";
}

export default function TasksPage() {
  const [data, setData] = useState<TasksResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const totalTasks = useMemo(
    () => data?.sections.reduce((total, section) => total + section.tasks.length, 0) ?? 0,
    [data],
  );

  async function loadTasks() {
    setIsLoading(true);
    setError(null);
    try {
      setData(await apiRequest<TasksResponse>("/tasks"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load tasks.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadTasks();
  }, []);

  return (
    <section className="mx-auto w-[calc(100vw-2rem)] max-w-6xl space-y-5 pb-6 sm:w-full">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-gold">Todoist</p>
          <h3 className="mt-2 text-3xl font-semibold text-pearl">{totalTasks} active tasks</h3>
          {error ? <p className="mt-2 text-sm text-coral">{error}</p> : null}
        </div>
        <button
          type="button"
          onClick={() => void loadTasks()}
          aria-label="Refresh tasks"
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
        >
          <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
        </button>
      </div>

      {data?.errors.length ? (
        <div className="rounded-lg border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Todoist read issue
          </div>
          <p className="mt-2 leading-6">{data.errors.join(" ")}</p>
        </div>
      ) : null}

      {isLoading && !data ? (
        <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
          Loading tasks
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-5">
          {(data?.sections ?? []).map((section) => (
            <section key={section.name} className="min-w-0 rounded-lg border border-white/10 bg-white/[0.055] p-4 shadow-card">
              <div className="mb-4 flex items-baseline justify-between gap-3">
                <h3 className="text-xl font-semibold text-pearl">{section.name}</h3>
                <span className="text-sm text-stone-500">{section.tasks.length}</span>
              </div>

              {section.tasks.length === 0 ? (
                <div className="rounded-lg bg-black/20 p-3 text-sm text-stone-500">Clear</div>
              ) : (
                <div className="space-y-2">
                  {section.tasks.map((task) => (
                    <article key={task.id ?? task.content} className="rounded-lg bg-black/20 p-3">
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 shrink-0 text-stone-500">
                          {task.completed ? (
                            <CheckCircle2 className="h-4 w-4 text-moss" aria-hidden="true" />
                          ) : (
                            <Circle className="h-4 w-4" aria-hidden="true" />
                          )}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="break-words text-sm font-medium leading-5 text-pearl">{task.content}</p>
                          {task.description ? (
                            <p className="mt-2 break-words text-xs leading-5 text-stone-500">{task.description}</p>
                          ) : null}
                        </div>
                        {task.url ? (
                          <a
                            href={task.url}
                            target="_blank"
                            rel="noreferrer"
                            aria-label="Open task in Todoist"
                            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-stone-500 hover:bg-white/[0.07] hover:text-pearl"
                          >
                            <ExternalLink className="h-4 w-4" aria-hidden="true" />
                          </a>
                        ) : null}
                      </div>

                      <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-medium">
                        <span className={`rounded-full border px-2 py-1 ${dueClass(task.due_status)}`}>
                          {formatDue(task)}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
                          {priorityLabel(task.priority)}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
                          {task.completed ? "done" : "open"}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
