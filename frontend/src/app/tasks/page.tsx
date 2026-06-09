"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  Circle,
  ExternalLink,
  Flag,
  Layers3,
  RefreshCw,
} from "lucide-react";
import { apiRequest, type TaskItem, type TaskSection, type TasksResponse } from "@/lib/api";

type TaskView = "today" | "upcoming" | "life-area";
type TaskFilter = "all" | "today" | "overdue" | "high";
type LifeArea = "A&M" | "XO" | "Nebulo" | "Freelance" | "Personal" | "Misc";

const lifeAreas: LifeArea[] = ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"];

const sectionToLifeArea: Record<string, LifeArea> = {
  "A&M": "A&M",
  "XO Collective": "XO",
  "Freelance Web Design": "Freelance",
  Nebulo: "Nebulo",
  Personal: "Personal",
  Misc: "Misc",
};

const lifeAreaToSection: Record<LifeArea, string> = {
  "A&M": "A&M",
  XO: "XO Collective",
  Freelance: "Freelance Web Design",
  Nebulo: "Nebulo",
  Personal: "Personal",
  Misc: "Misc",
};

const areaStyles: Record<LifeArea, { chip: string; dot: string; border: string; panel: string }> = {
  "A&M": {
    chip: "border-rose-300/35 bg-rose-300/10 text-rose-200",
    dot: "bg-rose-300",
    border: "border-l-rose-300",
    panel: "border-rose-300/25 bg-rose-300/[0.06]",
  },
  XO: {
    chip: "border-sky-300/35 bg-sky-300/10 text-sky-200",
    dot: "bg-sky-300",
    border: "border-l-sky-300",
    panel: "border-sky-300/25 bg-sky-300/[0.06]",
  },
  Nebulo: {
    chip: "border-iris/40 bg-iris/10 text-iris",
    dot: "bg-iris",
    border: "border-l-iris",
    panel: "border-iris/25 bg-iris/[0.06]",
  },
  Freelance: {
    chip: "border-moss/35 bg-moss/10 text-moss",
    dot: "bg-moss",
    border: "border-l-moss",
    panel: "border-moss/25 bg-moss/[0.06]",
  },
  Personal: {
    chip: "border-gold/40 bg-gold/10 text-gold",
    dot: "bg-gold",
    border: "border-l-gold",
    panel: "border-gold/25 bg-gold/[0.06]",
  },
  Misc: {
    chip: "border-stone-500/35 bg-white/[0.045] text-stone-300",
    dot: "bg-stone-400",
    border: "border-l-stone-500",
    panel: "border-white/10 bg-white/[0.045]",
  },
};

function taskLifeArea(task: TaskItem): LifeArea {
  const realSection = task.todoist_section_name || task.section_name || task.section;
  if (realSection && sectionToLifeArea[realSection]) {
    return sectionToLifeArea[realSection];
  }
  if (task.category && lifeAreas.includes(task.category as LifeArea)) {
    return task.category as LifeArea;
  }
  return "Misc";
}

function taskSectionName(task: TaskItem): string {
  return task.todoist_section_name || task.section_name || task.section || lifeAreaToSection[taskLifeArea(task)];
}

function dueDateValue(task: TaskItem): string | null {
  if (task.due_date) {
    return task.due_date;
  }
  const dueDate = task.due?.date;
  return typeof dueDate === "string" ? dueDate : null;
}

function formatDue(task: TaskItem): string {
  const dueDate = dueDateValue(task);
  if (!dueDate) {
    return "No due date";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(`${dueDate}T12:00:00`));
}

function priorityLabel(priority?: number | null) {
  return priority ? `P${priority}` : "P?";
}

function isHighPriority(task: TaskItem) {
  const todoistPriority = Number(task.todoist_priority ?? task.priority ?? 0);
  return todoistPriority >= 4;
}

function dueStateLabel(task: TaskItem) {
  if (task.due_status === "overdue") {
    return "Overdue";
  }
  if (task.due_status === "today") {
    return "Today";
  }
  if (task.due_status === "tomorrow") {
    return "Tomorrow";
  }
  if (task.due_status === "this_week") {
    return "This week";
  }
  if (task.due_status === "later") {
    return "Upcoming";
  }
  return "Anytime";
}

function dueClass(status?: string | null) {
  if (status === "overdue") {
    return "border-coral/30 bg-coral/10 text-coral";
  }
  if (status === "today") {
    return "border-gold/30 bg-gold/10 text-gold";
  }
  if (status === "tomorrow" || status === "this_week" || status === "later") {
    return "border-moss/30 bg-moss/10 text-moss";
  }
  return "border-white/10 bg-white/[0.06] text-stone-400";
}

function sortTasks(tasks: TaskItem[]) {
  const dueOrder: Record<string, number> = {
    overdue: 0,
    today: 1,
    tomorrow: 2,
    this_week: 3,
    later: 4,
  };

  return [...tasks].sort((first, second) => {
    const firstDue = dueOrder[first.due_status ?? ""] ?? 5;
    const secondDue = dueOrder[second.due_status ?? ""] ?? 5;
    if (firstDue !== secondDue) {
      return firstDue - secondDue;
    }

    const priorityDelta = Number(second.todoist_priority ?? second.priority ?? 0) - Number(first.todoist_priority ?? first.priority ?? 0);
    if (priorityDelta !== 0) {
      return priorityDelta;
    }

    const firstDate = dueDateValue(first) ?? "9999-12-31";
    const secondDate = dueDateValue(second) ?? "9999-12-31";
    return firstDate.localeCompare(secondDate);
  });
}

function filterTasks(tasks: TaskItem[], filter: TaskFilter) {
  if (filter === "today") {
    return tasks.filter((task) => task.due_status === "today");
  }
  if (filter === "overdue") {
    return tasks.filter((task) => task.due_status === "overdue");
  }
  if (filter === "high") {
    return tasks.filter(isHighPriority);
  }
  return tasks;
}

function flattenSections(sections: TaskSection[]) {
  return sections.flatMap((section) =>
    section.tasks.map((task) => ({
      ...task,
      section: task.section || section.name,
      todoist_section_name: task.todoist_section_name || task.section_name || section.name,
    })),
  );
}

function TaskCard({ task }: { task: TaskItem }) {
  const area = taskLifeArea(task);
  const styles = areaStyles[area];
  const sectionName = taskSectionName(task);

  return (
    <article className={`min-w-0 rounded-lg border border-l-4 bg-black/20 p-4 shadow-card ${styles.border}`}>
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 shrink-0 text-stone-500">
          {task.completed ? (
            <CheckCircle2 className="h-4 w-4 text-moss" aria-hidden="true" />
          ) : (
            <Circle className="h-4 w-4" aria-hidden="true" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-semibold leading-5 text-pearl">{task.content}</p>
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
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-stone-500 transition hover:bg-white/[0.07] hover:text-pearl"
          >
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
          </a>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-medium">
        <span className={`rounded-full border px-2 py-1 ${styles.chip}`}>{area}</span>
        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
          {sectionName}
        </span>
        <span className={`rounded-full border px-2 py-1 ${dueClass(task.due_status)}`}>
          {dueStateLabel(task)} · {formatDue(task)}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
          <Flag className="h-3 w-3" aria-hidden="true" />
          {priorityLabel(task.priority)}
        </span>
      </div>
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

function TaskList({ tasks, emptyLabel }: { tasks: TaskItem[]; emptyLabel: string }) {
  if (!tasks.length) {
    return <EmptyState label={emptyLabel} />;
  }

  return (
    <div className="space-y-3">
      {tasks.map((task) => (
        <TaskCard key={task.id ?? task.content} task={task} />
      ))}
    </div>
  );
}

export default function TasksPage() {
  const [data, setData] = useState<TasksResponse | null>(null);
  const [view, setView] = useState<TaskView>("today");
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tasks = useMemo(() => sortTasks(flattenSections(data?.sections ?? [])), [data]);
  const filteredTasks = useMemo(() => filterTasks(tasks, filter), [filter, tasks]);
  const todayTasks = useMemo(
    () => filteredTasks.filter((task) => task.due_status === "today" || task.due_status === "overdue"),
    [filteredTasks],
  );
  const upcomingTasks = useMemo(
    () => filteredTasks.filter((task) => ["tomorrow", "this_week", "later"].includes(task.due_status ?? "")),
    [filteredTasks],
  );
  const groupedByArea = useMemo(
    () =>
      lifeAreas.map((area) => ({
        area,
        sectionName: lifeAreaToSection[area],
        tasks: filteredTasks.filter((task) => taskLifeArea(task) === area),
      })),
    [filteredTasks],
  );

  const stats = useMemo(
    () => ({
      total: tasks.length,
      today: tasks.filter((task) => task.due_status === "today").length,
      overdue: tasks.filter((task) => task.due_status === "overdue").length,
      high: tasks.filter(isHighPriority).length,
    }),
    [tasks],
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
    <section className="mx-auto w-[calc(100vw-2rem)] max-w-7xl space-y-5 pb-6 sm:w-full">
      <div className="flex flex-col gap-4 rounded-lg border border-line bg-panel/80 p-4 shadow-card lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-gold">Todoist</p>
          <h3 className="mt-2 text-3xl font-semibold text-pearl md:text-4xl">Tasks command center</h3>
          <p className="mt-2 text-sm text-stone-400">
            {isLoading ? "Syncing tasks..." : `${stats.total} active tasks grouped by real Todoist sections`}
          </p>
          {error ? <p className="mt-2 text-sm text-coral">{error}</p> : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-line bg-black/20 p-1">
            {(["today", "upcoming", "life-area"] as TaskView[]).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setView(item)}
                className={`h-9 rounded-md px-3 text-sm font-medium capitalize transition ${
                  view === item ? "bg-white text-ink" : "text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
                }`}
              >
                {item === "life-area" ? "By Life Area" : item}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => void loadTasks()}
            aria-label="Refresh tasks"
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-stone-400 hover:bg-white/[0.06] hover:text-pearl"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-line bg-white/[0.04] p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Today</p>
          <p className="mt-2 text-2xl font-semibold text-pearl">{stats.today}</p>
        </div>
        <div className="rounded-lg border border-coral/25 bg-coral/10 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-coral">Overdue</p>
          <p className="mt-2 text-2xl font-semibold text-pearl">{stats.overdue}</p>
        </div>
        <div className="rounded-lg border border-moss/25 bg-moss/10 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-moss">High Priority</p>
          <p className="mt-2 text-2xl font-semibold text-pearl">{stats.high}</p>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Life Areas</p>
          <p className="mt-2 text-2xl font-semibold text-pearl">{lifeAreas.length}</p>
        </div>
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

      <div className="flex gap-2 overflow-x-auto rounded-lg border border-line bg-white/[0.035] p-2">
        {(["all", "today", "overdue", "high"] as TaskFilter[]).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setFilter(item)}
            className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-md border px-3 text-xs font-medium capitalize transition ${
              filter === item ? "border-gold/40 bg-gold/10 text-gold" : "border-white/10 bg-black/20 text-stone-400 hover:text-pearl"
            }`}
          >
            {item === "high" ? "High priority" : item}
          </button>
        ))}
      </div>

      {isLoading && !data ? (
        <EmptyState label="Loading Todoist tasks" />
      ) : (
        <>
          {view === "today" ? (
            <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <CalendarDays className="h-4 w-4 text-gold" aria-hidden="true" />
                  <h3 className="text-xl font-semibold text-pearl">Today Focus</h3>
                </div>
                <TaskList tasks={todayTasks} emptyLabel="No overdue or due-today tasks match this filter." />
              </div>

              <aside className="space-y-3">
                {lifeAreas.map((area) => {
                  const areaTasks = todayTasks.filter((task) => taskLifeArea(task) === area);
                  return (
                    <div key={area} className={`rounded-lg border p-4 ${areaStyles[area].panel}`}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span className={`h-2.5 w-2.5 rounded-full ${areaStyles[area].dot}`} />
                          <span className="text-sm font-medium text-pearl">{area}</span>
                        </div>
                        <span className="text-sm text-stone-400">{areaTasks.length}</span>
                      </div>
                    </div>
                  );
                })}
              </aside>
            </section>
          ) : null}

          {view === "upcoming" ? (
            <section className="grid gap-5 lg:grid-cols-3">
              {[
                { title: "Tomorrow", tasks: upcomingTasks.filter((task) => task.due_status === "tomorrow") },
                { title: "This Week", tasks: upcomingTasks.filter((task) => task.due_status === "this_week") },
                { title: "Later", tasks: upcomingTasks.filter((task) => task.due_status === "later" || !task.due_status) },
              ].map((group) => (
                <section key={group.title} className="min-w-0 rounded-lg border border-line bg-white/[0.035] p-4">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <h3 className="text-xl font-semibold text-pearl">{group.title}</h3>
                    <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1 text-xs text-stone-400">
                      {group.tasks.length}
                    </span>
                  </div>
                  <TaskList tasks={group.tasks} emptyLabel="Clear" />
                </section>
              ))}
            </section>
          ) : null}

          {view === "life-area" ? (
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {groupedByArea.map(({ area, sectionName, tasks: areaTasks }) => (
                <section key={area} className={`min-w-0 rounded-lg border p-4 shadow-card ${areaStyles[area].panel}`}>
                  <div className="mb-4 flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <Layers3 className="h-4 w-4 text-stone-500" aria-hidden="true" />
                        <h3 className="text-xl font-semibold text-pearl">{area}</h3>
                      </div>
                      <p className="mt-1 text-xs text-stone-500">Todoist section: {sectionName}</p>
                    </div>
                    <span className={`rounded-full border px-2 py-1 text-xs ${areaStyles[area].chip}`}>{areaTasks.length}</span>
                  </div>
                  <TaskList tasks={areaTasks} emptyLabel="Clear" />
                </section>
              ))}
            </section>
          ) : null}
        </>
      )}

      {!isLoading && data && filteredTasks.length === 0 && tasks.length > 0 ? (
        <div className="rounded-lg border border-line bg-white/[0.04] p-5 text-sm text-stone-400">
          No tasks match the current filter.
        </div>
      ) : null}

      <div className="rounded-lg border border-line bg-white/[0.035] p-4 text-xs leading-5 text-stone-500">
        <div className="flex items-center gap-2 text-stone-300">
          <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          Grouping is backed by Todoist section names and IDs from the To-Do project.
        </div>
      </div>
    </section>
  );
}
