"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ExternalLink,
  ListTodo,
  RefreshCw,
  Target,
  UserRound,
} from "lucide-react";
import {
  apiRequest,
  formatDateTime,
  type ActivityEntry,
  type CalendarEvent,
  type EvaluatedDependencyEvidence,
  type MemoryEntry,
  type ProjectBrain,
  type ProjectBlocker,
  type ProjectTaskDiagnostic,
  type ProjectTaskGroup,
  type ProjectWorkPackage,
  type TaskItem,
} from "@/lib/api";
import {
  currentDependencyEvidence,
  dependencyEvidencePresentation,
  packageAvailabilityPresentation,
  workPackageSectionState,
} from "@/lib/work-package-presentation";

function statusClass(status: string) {
  if (status === "Blocked") {
    return "border-coral/30 bg-coral/10 text-coral";
  }
  if (status === "Needs attention") {
    return "border-gold/30 bg-gold/10 text-gold";
  }
  if (status === "Active") {
    return "border-moss/30 bg-moss/10 text-moss";
  }
  return "border-white/10 bg-white/[0.06] text-stone-400";
}

function blockerClass(blocker: ProjectBlocker) {
  return blocker.severity === "critical"
    ? "border-coral/25 bg-coral/10 text-coral"
    : "border-gold/25 bg-gold/10 text-gold";
}

function Card({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[1.5rem] border border-white/10 bg-white/[0.055] p-5 shadow-card backdrop-blur-2xl">
      <div className="mb-5 flex items-center justify-between gap-4">
        <h4 className="text-lg font-semibold text-pearl">{title}</h4>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[0.07] text-moss">
          {icon}
        </div>
      </div>
      {children}
    </section>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4 text-sm text-stone-500">
      {text}
    </div>
  );
}

function eventRange(event: CalendarEvent) {
  return `${formatDateTime(event.start)} - ${new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(event.end))}`;
}

function taskDue(task: TaskItem) {
  if (task.due_status === "overdue") {
    return "Overdue";
  }
  if (task.due_status === "today") {
    return "Today";
  }
  if (task.due_date) {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
      new Date(`${task.due_date}T12:00:00`),
    );
  }
  return "Anytime";
}

function taskPriority(task: TaskItem) {
  return task.todoist_priority ?? task.priority ?? "?";
}

function TaskBadges({ task }: { task: TaskItem }) {
  return (
    <div className="mt-2 flex flex-wrap gap-2 text-[0.68rem]">
      <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
        {taskDue(task)}
      </span>
      <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
        P{taskPriority(task)}
      </span>
      {task.parent_id ? (
        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-stone-400">
          Subtask
        </span>
      ) : null}
    </div>
  );
}

function TaskRow({ task, nested = false }: { task: TaskItem; nested?: boolean }) {
  return (
    <article className={`${nested ? "bg-white/[0.035]" : "bg-black/20"} rounded-2xl p-4`}>
      <div className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-moss" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-semibold text-pearl">{task.content}</p>
          <TaskBadges task={task} />
        </div>
        {task.url ? (
          <a href={task.url} target="_blank" rel="noreferrer" className="text-stone-500 hover:text-moss" aria-label="Open Todoist task">
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
          </a>
        ) : null}
      </div>
    </article>
  );
}

function TaskGroup({ group }: { group: ProjectTaskGroup }) {
  const hasSubtasks = group.subtasks.length > 0;
  if (!hasSubtasks) {
    return <TaskRow task={group.parent_task} />;
  }

  return (
    <details className="group rounded-2xl bg-black/20 p-4" open>
      <summary className="flex cursor-pointer list-none items-start gap-3">
        <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-stone-500 transition group-open:rotate-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="break-words text-sm font-semibold text-pearl">{group.parent_task.content}</p>
            {group.is_container ? (
              <span className="rounded-full border border-iris/25 bg-iris/10 px-2 py-1 text-[0.68rem] text-iris">
                Container
              </span>
            ) : null}
          </div>
          <TaskBadges task={group.parent_task} />
        </div>
        <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-[0.68rem] text-stone-400">
          {group.subtasks.length}
        </span>
      </summary>
      <div className="mt-3 space-y-2 border-l border-white/10 pl-4">
        {group.subtasks.map((subtask) => (
          <TaskRow key={subtask.id ?? subtask.content} task={subtask} nested />
        ))}
      </div>
    </details>
  );
}

function DiagnosticRow({ diagnostic }: { diagnostic: ProjectTaskDiagnostic }) {
  return (
    <article className="rounded-2xl bg-black/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words text-sm font-semibold text-pearl">{diagnostic.task_title}</p>
          {diagnostic.parent_title ? (
            <p className="mt-1 break-words text-xs text-stone-500">Parent: {diagnostic.parent_title}</p>
          ) : null}
        </div>
        <span
          className={`rounded-full border px-2 py-1 text-[0.68rem] ${
            diagnostic.included
              ? "border-moss/25 bg-moss/10 text-moss"
              : "border-stone-500/25 bg-white/[0.045] text-stone-400"
          }`}
        >
          {diagnostic.included ? "Included" : "Excluded"}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-xs leading-5 text-stone-400 sm:grid-cols-2">
        <div>
          <dt className="text-stone-500">Project</dt>
          <dd className="break-words">{diagnostic.resolved_project}</dd>
        </div>
        <div>
          <dt className="text-stone-500">Section</dt>
          <dd className="break-words">{diagnostic.todoist_section ?? "None"}</dd>
        </div>
        <div>
          <dt className="text-stone-500">Priority</dt>
          <dd>{diagnostic.priority ? `P${diagnostic.priority}` : "None"}</dd>
        </div>
        <div>
          <dt className="text-stone-500">Reason</dt>
          <dd className="break-words">{diagnostic.reason}</dd>
        </div>
      </dl>
    </article>
  );
}

function ActivityRow({ activity }: { activity: ActivityEntry }) {
  return (
    <article className="rounded-2xl bg-black/20 p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-xs uppercase tracking-[0.18em] text-stone-500">
          {(activity.type || activity.action_type).replaceAll("_", " ")}
        </p>
        <p className="break-words text-sm font-medium text-pearl">{activity.title}</p>
      </div>
      <p className="mt-2 text-xs leading-5 text-stone-500">
        {activity.description || activity.detail || formatDateTime(activity.created_at)}
      </p>
    </article>
  );
}

function MemoryRow({ memory }: { memory: MemoryEntry }) {
  return (
    <article className="rounded-2xl bg-black/20 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-[0.68rem] uppercase tracking-[0.14em] text-stone-500">
          {memory.type}
        </span>
        <p className="break-words text-sm font-medium text-pearl">{memory.title}</p>
      </div>
      <p className="mt-2 text-sm leading-6 text-stone-400">{memory.content}</p>
    </article>
  );
}

function WorkPackageOption({ workPackage }: { workPackage: ProjectWorkPackage }) {
  const availability = packageAvailabilityPresentation(workPackage.availability_state);
  const toneClass =
    availability.tone === "available"
      ? "border-moss/25 bg-moss/10 text-moss"
      : availability.tone === "warning"
        ? "border-gold/25 bg-gold/10 text-gold"
        : "border-white/10 bg-white/[0.06] text-stone-400";

  return (
    <article className="rounded-2xl border border-white/10 bg-black/20 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words text-lg font-semibold text-pearl">{workPackage.title}</p>
          <p className="mt-1 text-xs text-stone-500">{workPackage.context}</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[0.68rem] ${toneClass}`}>
          {availability.label}
        </span>
      </div>
      <p className="mt-4 text-sm text-stone-400">
        {workPackage.open_action_count} open action{workPackage.open_action_count === 1 ? "" : "s"}
        {workPackage.explicitly_blocked_action_count > 0
          ? ` · ${workPackage.explicitly_blocked_action_count} explicitly blocked`
          : ""}
        {workPackage.needs_review_action_count > 0
          ? ` · ${workPackage.needs_review_action_count} needs review`
          : ""}
      </p>
      {workPackage.next_action ? (
        <div className="mt-4 rounded-xl bg-white/[0.055] p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-moss">Next action</p>
          <p className="mt-2 break-words text-sm font-semibold text-pearl">
            {workPackage.next_action.title}
          </p>
          <p className="mt-2 text-xs leading-5 text-stone-500">
            {workPackage.next_action.explanation}
          </p>
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6 text-stone-500">{availability.detail}</p>
      )}
      {workPackage.provider_url ? (
        <a
          href={workPackage.provider_url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-flex items-center gap-1.5 text-xs text-moss hover:text-pearl"
        >
          Open in Linear
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        </a>
      ) : null}
    </article>
  );
}

function DependencyEvidenceRow({ evidence }: { evidence: EvaluatedDependencyEvidence }) {
  const presentation = dependencyEvidencePresentation(evidence.evaluation_state);
  const stateClass = presentation.tone === "warning"
    ? "border-gold/25 bg-gold/10 text-gold"
    : "border-coral/25 bg-coral/10 text-coral";
  const blockedLabel = evidence.blocked_work.provider_identifier ?? evidence.blocked_work.title ?? "Blocked work";
  const blockerLabel = evidence.blocking_work.provider_identifier ?? evidence.blocking_work.title ?? "Unknown blocker";

  return (
    <article className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`rounded-full border px-2 py-1 text-[0.68rem] ${stateClass}`}>
          {presentation.label}
        </span>
        <span className="text-[0.68rem] uppercase tracking-[0.14em] text-stone-500">Linear evidence</span>
      </div>
      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-[1fr_auto_1fr] sm:items-center">
        <div>
          <p className="text-xs text-stone-500">Blocked work</p>
          <p className="mt-1 break-words font-semibold text-pearl">{blockedLabel}</p>
          <p className="mt-1 text-xs capitalize text-stone-500">{evidence.blocked_work.status ?? "Unknown status"}</p>
        </div>
        <span className="hidden text-stone-600 sm:block">←</span>
        <div>
          <p className="text-xs text-stone-500">Blocking work</p>
          <p className="mt-1 break-words font-semibold text-pearl">{blockerLabel}</p>
          <p className="mt-1 text-xs capitalize text-stone-500">{evidence.blocking_work.status ?? "Unknown status"}</p>
        </div>
      </div>
      <p className="mt-3 text-xs leading-5 text-stone-400">{evidence.explanation}</p>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-moss">
        {evidence.blocked_work.provider_url ? (
          <a href={evidence.blocked_work.provider_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-pearl">
            Open {blockedLabel}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        ) : null}
        {evidence.blocking_work.provider_url ? (
          <a href={evidence.blocking_work.provider_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-pearl">
            Open {blockerLabel}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        ) : null}
      </div>
    </article>
  );
}

export default function ProjectDetailPage() {
  const params = useParams<{ projectKey: string }>();
  const projectKey = params.projectKey;
  const [project, setProject] = useState<ProjectBrain | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectKey) {
      return;
    }

    setIsLoading(true);
    apiRequest<ProjectBrain>(`/projects/${projectKey}`)
      .then((payload) => {
        setProject(payload);
        setError(null);
      })
      .catch((requestError) => {
        setError(requestError instanceof Error ? requestError.message : "Unable to load project.");
      })
      .finally(() => setIsLoading(false));
  }, [projectKey]);

  const heroStats = useMemo(() => {
    if (!project) {
      return [];
    }
    return [
      { label: "Tasks", value: project.task_count ?? project.tasks.length },
      { label: "Events", value: project.upcoming_events.length },
      { label: "Blockers", value: project.blockers.length },
      { label: "Memories", value: project.memories.length },
    ];
  }, [project]);

  const packageSectionState = project
    ? workPackageSectionState(project.work_packages ?? [], project.linear_diagnostic ?? null)
    : "hidden";
  const currentDependencyBlockers = currentDependencyEvidence(
    project?.dependency_evidence ?? [],
  );

  if (isLoading) {
    return (
      <div className="mx-auto w-[calc(100vw-2rem)] max-w-6xl space-y-4 pb-6 sm:w-full">
        <div className="h-72 animate-pulse rounded-[2rem] border border-white/10 bg-white/[0.055]" />
        <div className="grid gap-4 xl:grid-cols-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="h-56 animate-pulse rounded-[1.5rem] border border-white/10 bg-white/[0.055]" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="mx-auto w-[calc(100vw-2rem)] max-w-4xl pb-6 sm:w-full">
        <Link href="/projects" className="mb-4 inline-flex items-center gap-2 text-sm text-stone-400 hover:text-moss">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Projects
        </Link>
        <div className="rounded-[1.5rem] border border-coral/25 bg-coral/10 p-5 text-coral">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Project unavailable
          </div>
          <p className="mt-2 text-sm leading-6">{error || "Project not found."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-[calc(100vw-2rem)] max-w-6xl space-y-5 pb-6 sm:w-full">
      <Link href="/projects" className="inline-flex items-center gap-2 text-sm text-stone-400 hover:text-moss">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Projects
      </Link>

      <section className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-6 shadow-soft backdrop-blur-2xl md:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-moss">Project</p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <h3 className="text-4xl font-semibold tracking-normal text-pearl md:text-6xl">
                {project.name}
              </h3>
              <span className={`rounded-full border px-3 py-1 text-xs font-medium ${statusClass(project.status)}`}>
                {project.status}
              </span>
            </div>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-stone-400">{project.description}</p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:min-w-[26rem] sm:grid-cols-4">
            {heroStats.map((stat) => (
              <div key={stat.label} className="rounded-2xl bg-black/20 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-stone-500">{stat.label}</p>
                <p className="mt-2 text-3xl font-semibold text-pearl">{stat.value}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {packageSectionState !== "hidden" ? (
        <section className="rounded-[1.5rem] border border-white/10 bg-white/[0.055] p-5 shadow-card backdrop-blur-2xl md:p-6">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.22em] text-moss">Project workspace</p>
              <h4 className="mt-2 text-2xl font-semibold text-pearl">Work on {project.name} now?</h4>
            </div>
            {project.linear_diagnostic?.status === "connected" ? (
              <span className="text-xs text-stone-500">
                {project.linear_diagnostic.issue_count} mapped Linear issue{project.linear_diagnostic.issue_count === 1 ? "" : "s"}
              </span>
            ) : null}
          </div>
          {packageSectionState === "options" ? (
            <div className="grid gap-3 lg:grid-cols-3">
              {project.work_packages.slice(0, 3).map((workPackage) => (
                <WorkPackageOption key={workPackage.package_id} workPackage={workPackage} />
              ))}
            </div>
          ) : packageSectionState === "unavailable" ? (
            <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4 text-sm leading-6 text-gold">
              {project.linear_diagnostic?.message ?? "Linear work is temporarily unavailable."}
            </div>
          ) : (
            <EmptyState text="No current Linear work packages have open actions." />
          )}
        </section>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-3">
        <Card title="Next move" icon={<Target className="h-5 w-5" aria-hidden="true" />}>
          <div className="rounded-2xl bg-moss/10 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-moss">Next move</p>
            <p className="mt-3 text-2xl font-semibold leading-tight text-pearl">
              {project.next_recommendation}
            </p>
          </div>
        </Card>

        <Card title="Explicit blockers" icon={<AlertTriangle className="h-5 w-5" aria-hidden="true" />}>
          {currentDependencyBlockers.length === 0 ? (
            <EmptyState text="No active or needs-review dependencies." />
          ) : (
            <div className="space-y-3">
              {currentDependencyBlockers.map((evidence) => (
                <DependencyEvidenceRow
                  key={`${evidence.blocked_work.provider_record_id}-${evidence.blocking_work.provider_record_id}`}
                  evidence={evidence}
                />
              ))}
            </div>
          )}
        </Card>

        <Card title="Attention signals" icon={<AlertTriangle className="h-5 w-5" aria-hidden="true" />}>
          {project.attention_signals.length === 0 ? (
            <EmptyState text="No heuristic attention signals." />
          ) : (
            <div className="space-y-3">
              {project.attention_signals.map((signal, index) => (
                <article key={`${signal.type}-${signal.source_id ?? index}`} className={`rounded-2xl border p-4 ${blockerClass(signal)}`}>
                  <p className="text-sm font-semibold">{signal.title}</p>
                  {signal.detail ? <p className="mt-2 text-xs leading-5 text-stone-200">{signal.detail}</p> : null}
                </article>
              ))}
            </div>
          )}
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card title="Upcoming events" icon={<CalendarClock className="h-5 w-5" aria-hidden="true" />}>
          {project.upcoming_events.length === 0 ? (
            <EmptyState text="No upcoming events found." />
          ) : (
            <div className="space-y-3">
              {project.upcoming_events.map((event) => (
                <article key={event.id ?? `${event.title}-${event.start}`} className="rounded-2xl bg-black/20 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="break-words text-sm font-semibold text-pearl">{event.title}</p>
                      <p className="mt-2 flex items-center gap-1.5 text-xs text-stone-400">
                        <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                        {eventRange(event)}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-[0.68rem] capitalize text-stone-400">
                      {event.event_category || event.event_type}
                    </span>
                  </div>
                  {event.html_link ? (
                    <a
                      href={event.html_link}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-flex items-center gap-1.5 text-xs text-moss hover:text-pearl"
                    >
                      Open
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  ) : null}
                </article>
              ))}
            </div>
          )}
        </Card>

        <Card title="Tasks" icon={<ListTodo className="h-5 w-5" aria-hidden="true" />}>
          {project.task_groups.length === 0 ? (
            <EmptyState text="No matching Todoist tasks." />
          ) : (
            <div className="space-y-3">
              {project.task_groups.map((group) => (
                <TaskGroup key={group.parent_task.id ?? group.parent_task.content} group={group} />
              ))}
            </div>
          )}
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <Card title="People" icon={<UserRound className="h-5 w-5" aria-hidden="true" />}>
          {project.people.length === 0 ? (
            <EmptyState text="No people attached." />
          ) : (
            <div className="flex flex-wrap gap-2">
              {project.people.map((person) => (
                <span key={person} className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-2 text-sm text-stone-300">
                  {person}
                </span>
              ))}
            </div>
          )}
        </Card>

        <Card title="Memory/context" icon={<RefreshCw className="h-5 w-5" aria-hidden="true" />}>
          {project.memories.length === 0 ? (
            <EmptyState text="No matching memory entries." />
          ) : (
            <div className="space-y-3">
              {project.memories.map((memory) => (
                <MemoryRow key={memory.id} memory={memory} />
              ))}
            </div>
          )}
        </Card>

        <Card title="Recent activity" icon={<Clock3 className="h-5 w-5" aria-hidden="true" />}>
          {project.recent_activity.length === 0 ? (
            <EmptyState text="No recent activity found." />
          ) : (
            <div className="space-y-3">
              {project.recent_activity.map((activity) => (
                <ActivityRow key={activity.id} activity={activity} />
              ))}
            </div>
          )}
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-1">
        <Card title="Classification diagnostics" icon={<ListTodo className="h-5 w-5" aria-hidden="true" />}>
          {project.classification_diagnostics.length === 0 ? (
            <EmptyState text="No task diagnostics available." />
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {project.classification_diagnostics.slice(0, 40).map((diagnostic, index) => (
                <DiagnosticRow key={`${diagnostic.task_title}-${diagnostic.parent_title ?? "root"}-${index}`} diagnostic={diagnostic} />
              ))}
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
