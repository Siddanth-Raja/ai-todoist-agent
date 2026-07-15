"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarDays,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Circle,
  ExternalLink,
  Flag,
  Layers3,
  RefreshCw,
} from "lucide-react";
import { apiRequest, type TaskItem, type TaskSection, type TasksResponse } from "@/lib/api";
import { formatTaskDate, taskDateTime, taskDueDateValue } from "@/lib/task-date";

type TaskView = "today" | "upcoming" | "life-area";
type TaskFilter = "all" | "today" | "overdue" | "high";
type LifeArea = "A&M" | "XO" | "Nebulo" | "Freelance" | "Personal" | "Misc";
type FocusRecommendation = {
  area: LifeArea;
  sectionName: string;
  task: TaskItem | null;
  reason: string;
  taskCount: number;
  tasks: TaskItem[];
};
type RecommendationScore = {
  priority: number;
  age: number;
  unblocking: number;
  momentum: number;
  due: number;
};
type RecommendationSnapshot = {
  area: LifeArea;
  taskId: string | null;
  taskContent: string | null;
  score: RecommendationScore | null;
};
type RecommendationChange = {
  area: LifeArea;
  previous: string;
  current: string;
  reason: string;
};

const lifeAreas: LifeArea[] = ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"];
const recommendationStorageKey = "pcos.taskRecommendations.v1";

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

function compareTaskDates(first: TaskItem, second: TaskItem): number {
  const firstDate = taskDateTime(taskDueDateValue(first));
  const secondDate = taskDateTime(taskDueDateValue(second));
  if (firstDate === null) {
    return secondDate === null ? 0 : 1;
  }
  if (secondDate === null) {
    return -1;
  }
  return firstDate - secondDate;
}

function formatDue(task: TaskItem): string {
  const dueDate = taskDueDateValue(task);
  return formatTaskDate(
    dueDate,
    { month: "short", day: "numeric" },
    "No due date",
  );
}

function priorityLabel(priority?: number | null) {
  return priority ? `P${priority}` : "P?";
}

function todoistPriorityValue(task: TaskItem) {
  return Number(task.todoist_priority ?? (task.priority ? 5 - task.priority : 0));
}

function isHighPriority(task: TaskItem) {
  return todoistPriorityValue(task) >= 4;
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

    return compareTaskDates(first, second);
  });
}

function taskKey(task: TaskItem) {
  return task.id ?? `${task.content}-${taskSectionName(task)}`;
}

function normalizedTaskText(task: TaskItem) {
  return `${task.content} ${task.description ?? ""} ${(task.labels ?? []).join(" ")}`.toLowerCase();
}

function dueUrgencyScore(task: TaskItem) {
  if (task.due_status === "overdue") {
    return 5;
  }
  if (task.due_status === "today") {
    return 4;
  }
  if (task.due_status === "tomorrow") {
    return 3;
  }
  if (task.due_status === "this_week") {
    return 2;
  }
  if (task.due_status === "later" || taskDueDateValue(task)) {
    return 1;
  }
  return 0;
}

function ageScore(task: TaskItem) {
  const createdAt = createdAtTime(task);
  if (createdAt === null) {
    return 0;
  }

  const ageDays = Math.max(0, Math.floor((Date.now() - createdAt) / 86_400_000));
  return Math.min(ageDays, 30);
}

function unblockingScore(task: TaskItem) {
  const text = normalizedTaskText(task);
  let score = 0;

  if (/\bbuild\b/.test(text)) {
    score += 2;
  }
  if (/\bsetup\b|\bset up\b/.test(text)) {
    score += 2;
  }
  if (text.includes("create system")) {
    score += 3;
  }
  if (/\bfoundation\b|\bfoundational\b/.test(text)) {
    score += 3;
  }
  if (/\btool\b|\btemplate\b|\bworkflow\b|\baccount\b/.test(text)) {
    score += 1;
  }

  return score;
}

function projectMomentumScore(task: TaskItem, areaTasks: TaskItem[]) {
  const text = normalizedTaskText(task);
  let score = 0;

  if (/\bdemo\b|\bclient\b|\boutreach\b|\bproposal\b|\bship\b|\blaunch\b|\bpublish\b|\bsend\b/.test(text)) {
    return 3;
  }

  const siblingTasks = areaTasks.filter((candidate) => taskKey(candidate) !== taskKey(task));
  if (task.project_name && siblingTasks.some((candidate) => candidate.project_name === task.project_name)) {
    score += 1;
  }
  if (task.labels?.length && siblingTasks.some((candidate) => candidate.labels?.some((label) => task.labels.includes(label)))) {
    score += 1;
  }

  return score;
}

function createdAtTime(task: TaskItem) {
  return taskDateTime(task.created_at);
}

function recommendationScore(task: TaskItem, areaTasks: TaskItem[]): RecommendationScore {
  return {
    priority: todoistPriorityValue(task),
    age: ageScore(task),
    unblocking: unblockingScore(task),
    momentum: projectMomentumScore(task, areaTasks),
    due: dueUrgencyScore(task),
  };
}

function compareRecommendationScores(first: RecommendationScore, second: RecommendationScore) {
  const priorityDelta = second.priority - first.priority;
  if (priorityDelta !== 0) {
    return priorityDelta;
  }

  const ageDelta = second.age - first.age;
  if (ageDelta !== 0) {
    return ageDelta;
  }

  const unblockingDelta = second.unblocking - first.unblocking;
  if (unblockingDelta !== 0) {
    return unblockingDelta;
  }

  const momentumDelta = second.momentum - first.momentum;
  if (momentumDelta !== 0) {
    return momentumDelta;
  }

  const dueDelta = second.due - first.due;
  if (dueDelta !== 0) {
    return dueDelta;
  }

  return 0;
}

function rankRecommendedTasks(tasks: TaskItem[]) {
  return [...tasks].sort((first, second) => {
    const scoreDelta = compareRecommendationScores(recommendationScore(first, tasks), recommendationScore(second, tasks));

    if (scoreDelta !== 0) {
      return scoreDelta;
    }

    const dueDateDelta = compareTaskDates(first, second);
    if (dueDateDelta !== 0) {
      return dueDateDelta;
    }

    return first.content.localeCompare(second.content);
  });
}

function focusReason(area: LifeArea, task: TaskItem, areaTasks: TaskItem[]) {
  const score = recommendationScore(task, areaTasks);
  const text = normalizedTaskText(task);

  if (area === "Freelance" && /\bbuild\b/.test(text) && /\b(scrap\w*|outreach|client|tool)\b/.test(text)) {
    return "This unlocks future client outreach.";
  }
  if (area === "Nebulo" && /\bdemo\b/.test(text)) {
    return "Closest task to external progress.";
  }
  if (area === "Personal" && /\b(invest\w*|account|setup|set up)\b/.test(text)) {
    return "One-time setup with long-term benefit.";
  }
  if (areaTasks.length === 1) {
    return `Only active ${area} task`;
  }
  if (score.priority >= 4 && score.unblocking > 0) {
    return "High-priority foundation task that unlocks later work.";
  }
  if (score.unblocking > 0) {
    return "Foundation task that unlocks follow-on work.";
  }
  if (score.momentum > 0) {
    return "Closest task to visible project progress.";
  }
  if (task.due_status === "overdue") {
    return `Overdue task in ${area}.`;
  }
  if (todoistPriorityValue(task) === Math.max(...areaTasks.map(todoistPriorityValue))) {
    return `Highest Todoist priority in ${area}.`;
  }
  if (score.age >= 14) {
    return "Older task with enough weight to clear next.";
  }
  if (task.due_status === "today") {
    return `Due today in ${area}.`;
  }
  return `Best next task in ${area}.`;
}

function recommendedByLifeArea(tasks: TaskItem[]): FocusRecommendation[] {
  return lifeAreas.map((area) => {
    const areaTasks = tasks.filter((task) => taskLifeArea(task) === area);
    const rankedTasks = rankRecommendedTasks(areaTasks);
    const task = rankedTasks[0] ?? null;
    return {
      area,
      sectionName: lifeAreaToSection[area],
      task,
      reason: task ? focusReason(area, task, areaTasks) : `No active ${area} tasks`,
      taskCount: areaTasks.length,
      tasks: rankedTasks,
    };
  });
}

function recommendationSnapshots(recommendations: FocusRecommendation[]): RecommendationSnapshot[] {
  return recommendations.map((recommendation) => ({
    area: recommendation.area,
    taskId: recommendation.task?.id ?? null,
    taskContent: recommendation.task?.content ?? null,
    score: recommendation.task ? recommendationScore(recommendation.task, recommendation.tasks) : null,
  }));
}

function readStoredRecommendationState(): { updatedAt: string | null; snapshots: RecommendationSnapshot[] } {
  if (typeof window === "undefined") {
    return { updatedAt: null, snapshots: [] };
  }

  try {
    const rawValue = window.localStorage.getItem(recommendationStorageKey);
    if (!rawValue) {
      return { updatedAt: null, snapshots: [] };
    }

    const parsed = JSON.parse(rawValue) as Partial<{ updatedAt: string | null; snapshots: RecommendationSnapshot[] }>;
    return {
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : null,
      snapshots: Array.isArray(parsed.snapshots) ? parsed.snapshots : [],
    };
  } catch {
    return { updatedAt: null, snapshots: [] };
  }
}

function writeStoredRecommendationState(updatedAt: string, snapshots: RecommendationSnapshot[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(recommendationStorageKey, JSON.stringify({ updatedAt, snapshots }));
}

function recommendationChanged(previous: RecommendationSnapshot, current: RecommendationSnapshot) {
  if (previous.taskId && current.taskId) {
    return previous.taskId !== current.taskId;
  }
  return previous.taskContent !== current.taskContent;
}

function changeReason(previous: RecommendationSnapshot, current: RecommendationSnapshot) {
  if (!previous.taskContent) {
    return "New recommendation after refresh.";
  }
  if (!current.score || !previous.score) {
    return "Recommendation changed after refresh.";
  }
  if (current.score.priority > previous.score.priority) {
    return "Higher-priority task added.";
  }
  if (current.score.age > previous.score.age) {
    return "Older task now needs attention.";
  }
  if (current.score.unblocking > previous.score.unblocking) {
    return "Current task unlocks more follow-on work.";
  }
  if (current.score.momentum > previous.score.momentum) {
    return "Current task is closer to external progress.";
  }
  if (current.score.due > previous.score.due) {
    return "Due date became more urgent.";
  }
  return "Recommendation changed after refresh.";
}

function recommendationChanges(
  previousSnapshots: RecommendationSnapshot[],
  currentSnapshots: RecommendationSnapshot[],
): RecommendationChange[] {
  return currentSnapshots.flatMap((current) => {
    const previous = previousSnapshots.find((snapshot) => snapshot.area === current.area);
    if (!previous || !current.taskContent || !recommendationChanged(previous, current)) {
      return [];
    }

    return [
      {
        area: current.area,
        previous: previous.taskContent ?? "No recommendation",
        current: current.taskContent,
        reason: changeReason(previous, current),
      },
    ];
  });
}

function formatUpdatedAgo(updatedAt: string | null, nowMs: number) {
  if (!updatedAt) {
    return "Not refreshed yet";
  }

  const updatedMs = taskDateTime(updatedAt);
  if (updatedMs === null) {
    return "Updated recently";
  }

  const elapsedSeconds = Math.max(0, Math.floor((nowMs - updatedMs) / 1000));
  if (elapsedSeconds < 60) {
    return "Updated just now";
  }

  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) {
    return `Updated ${elapsedMinutes} minute${elapsedMinutes === 1 ? "" : "s"} ago`;
  }

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) {
    return `Updated ${elapsedHours} hour${elapsedHours === 1 ? "" : "s"} ago`;
  }

  const elapsedDays = Math.floor(elapsedHours / 24);
  return `Updated ${elapsedDays} day${elapsedDays === 1 ? "" : "s"} ago`;
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

function TaskCard({ task, reason }: { task: TaskItem; reason?: string }) {
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
          {reason ? (
            <p className="mt-2 inline-flex rounded-full border border-gold/30 bg-gold/10 px-2 py-1 text-[11px] font-medium text-gold">
              {reason}
            </p>
          ) : null}
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
        <TaskCard key={taskKey(task)} task={task} />
      ))}
    </div>
  );
}

function FocusByArea({
  recommendations,
  changesByArea,
  isLoading,
  onRefresh,
  updatedLabel,
}: {
  recommendations: FocusRecommendation[];
  changesByArea: Partial<Record<LifeArea, RecommendationChange>>;
  isLoading: boolean;
  onRefresh: () => void;
  updatedLabel: string;
}) {
  const [expandedAreas, setExpandedAreas] = useState<Partial<Record<LifeArea, boolean>>>({});

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Focus by Life Area</p>
          <h3 className="mt-1 text-xl font-semibold text-pearl">Best next task in each section</h3>
          <p className="mt-1 text-xs text-stone-500">{updatedLabel}</p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-gold/30 bg-gold/10 px-3 text-sm font-medium text-gold transition hover:bg-gold/15"
        >
          <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
          Refresh recommendation
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {recommendations.map((item) => {
          const isExpanded = Boolean(expandedAreas[item.area]);
          const visibleTasks = isExpanded ? item.tasks : item.task ? [item.task] : [];
          const change = changesByArea[item.area];

          return (
            <section key={item.area} className={`min-w-0 rounded-lg border p-4 shadow-card ${areaStyles[item.area].panel}`}>
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${areaStyles[item.area].dot}`} />
                    <h4 className="text-base font-semibold text-pearl">{item.area}</h4>
                  </div>
                  <p className="mt-1 text-xs text-stone-500">Todoist section: {item.sectionName}</p>
                </div>
                <span className={`rounded-full border px-2 py-1 text-xs ${areaStyles[item.area].chip}`}>
                  {item.taskCount}
                </span>
              </div>

              {visibleTasks.length ? (
                <div className="space-y-3">
                  {visibleTasks.map((task) => {
                    const isRecommendedTask = item.task ? taskKey(task) === taskKey(item.task) : false;

                    return (
                      <TaskCard
                        key={taskKey(task)}
                        task={task}
                        reason={isRecommendedTask ? item.reason : undefined}
                      />
                    );
                  })}
                </div>
              ) : (
                <EmptyState label={item.reason} />
              )}

              {change ? (
                <div className="mt-3 rounded-lg border border-gold/25 bg-gold/10 p-3 text-xs leading-5 text-gold">
                  <p className="font-semibold text-pearl">Recommendation changed</p>
                  <p className="mt-2">
                    <span className="text-stone-400">Previous:</span> {change.previous}
                  </p>
                  <p>
                    <span className="text-stone-400">Current:</span> {change.current}
                  </p>
                  <p>
                    <span className="text-stone-400">Reason:</span> {change.reason}
                  </p>
                </div>
              ) : null}

              {item.taskCount > 1 ? (
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  onClick={() => setExpandedAreas((current) => ({ ...current, [item.area]: !isExpanded }))}
                  className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 text-xs font-medium text-stone-300 transition hover:bg-white/[0.06] hover:text-pearl"
                >
                  {isExpanded ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
                  {isExpanded ? "Collapse" : "Expand"}
                </button>
              ) : null}
            </section>
          );
        })}
      </div>
    </section>
  );
}

export default function TasksPage() {
  const [data, setData] = useState<TasksResponse | null>(null);
  const [view, setView] = useState<TaskView>("today");
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recommendationUpdatedAt, setRecommendationUpdatedAt] = useState<string | null>(null);
  const [recommendationChangeList, setRecommendationChangeList] = useState<RecommendationChange[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const recommendationSnapshotsRef = useRef<RecommendationSnapshot[] | null>(null);

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
  const focusRecommendations = useMemo(() => recommendedByLifeArea(tasks), [tasks]);
  const recommendationChangesByArea = useMemo(
    () =>
      recommendationChangeList.reduce<Partial<Record<LifeArea, RecommendationChange>>>((changes, change) => {
        changes[change.area] = change;
        return changes;
      }, {}),
    [recommendationChangeList],
  );
  const updatedLabel = useMemo(() => formatUpdatedAgo(recommendationUpdatedAt, nowMs), [nowMs, recommendationUpdatedAt]);
  const areaCounts = useMemo(
    () =>
      lifeAreas.reduce<Record<LifeArea, number>>((counts, area) => {
        counts[area] = tasks.filter((task) => taskLifeArea(task) === area).length;
        return counts;
      }, {} as Record<LifeArea, number>),
    [tasks],
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

  const loadTasks = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const nextData = await apiRequest<TasksResponse>("/tasks");
      const refreshedTasks = sortTasks(flattenSections(nextData.sections));
      const nextRecommendations = recommendedByLifeArea(refreshedTasks);
      const nextSnapshots = recommendationSnapshots(nextRecommendations);
      const storedState = readStoredRecommendationState();
      const previousSnapshots = recommendationSnapshotsRef.current ?? storedState.snapshots;
      const updatedAt = new Date().toISOString();

      recommendationSnapshotsRef.current = nextSnapshots;
      setData(nextData);
      setRecommendationUpdatedAt(updatedAt);
      setRecommendationChangeList(recommendationChanges(previousSnapshots, nextSnapshots));
      writeStoredRecommendationState(updatedAt, nextSnapshots);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load tasks.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const storedState = readStoredRecommendationState();
    recommendationSnapshotsRef.current = storedState.snapshots.length ? storedState.snapshots : null;
    setRecommendationUpdatedAt(storedState.updatedAt);
    void loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    const interval = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(interval);
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
                  <h3 className="text-xl font-semibold text-pearl">Recommended Focus</h3>
                </div>
                {todayTasks.length === 0 && filter === "all" ? (
                  <div className="rounded-lg border border-gold/25 bg-gold/10 p-4 text-sm text-gold">
                    Nothing due today. Here are the best next tasks by area.
                  </div>
                ) : null}
                <FocusByArea
                  recommendations={focusRecommendations}
                  changesByArea={recommendationChangesByArea}
                  isLoading={isLoading}
                  onRefresh={() => void loadTasks()}
                  updatedLabel={updatedLabel}
                />

                <section className="space-y-3 pt-2">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-base font-semibold text-pearl">Due-date queue</h4>
                    <span className="text-xs text-stone-500">Filters still apply here</span>
                  </div>
                  <TaskList tasks={todayTasks} emptyLabel="No overdue or due-today tasks match this filter." />
                </section>
              </div>

              <aside className="space-y-3">
                {lifeAreas.map((area) => {
                  return (
                    <div key={area} className={`rounded-lg border p-4 ${areaStyles[area].panel}`}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span className={`h-2.5 w-2.5 rounded-full ${areaStyles[area].dot}`} />
                          <span className="text-sm font-medium text-pearl">{area}</span>
                        </div>
                        <span className="text-sm text-stone-400">{areaCounts[area]}</span>
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
