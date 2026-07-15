"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  FolderKanban,
  ListTodo,
  RefreshCw,
} from "lucide-react";
import { apiRequest, type ProjectBrain } from "@/lib/api";
import { projectDependencyMetricLabels } from "@/lib/work-package-presentation";

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

function projectMetricLabel(project: ProjectBrain) {
  const parts = [
    `${project.task_count ?? project.tasks.length} tasks`,
    `${project.upcoming_events.length} events`,
    ...projectDependencyMetricLabels(project.dependency_summary),
  ];
  return parts.join(" - ");
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectBrain[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<ProjectBrain[]>("/projects")
      .then((payload) => {
        setProjects(payload);
        setError(null);
      })
      .catch((requestError) => {
        setError(requestError instanceof Error ? requestError.message : "Unable to load projects.");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const activeCount = useMemo(
    () => projects.filter((project) => project.status !== "Quiet").length,
    [projects],
  );

  return (
    <div className="mx-auto w-[calc(100vw-2rem)] max-w-6xl space-y-6 pb-6 sm:w-full">
      <section className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-6 shadow-soft backdrop-blur-2xl md:p-8">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-moss">Project Brain</p>
            <h3 className="mt-3 text-4xl font-semibold tracking-normal text-pearl md:text-6xl">
              Projects
            </h3>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-stone-400">
              Project pages collect next move, blockers, tasks, events, people, memory, and recent activity.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:min-w-80">
            <div className="rounded-2xl bg-black/20 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Active</p>
              <p className="mt-2 text-3xl font-semibold text-pearl">{activeCount}</p>
            </div>
            <div className="rounded-2xl bg-black/20 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Total</p>
              <p className="mt-2 text-3xl font-semibold text-pearl">{projects.length || 6}</p>
            </div>
          </div>
        </div>
      </section>

      {error ? (
        <div className="rounded-[1.4rem] border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Projects unavailable
          </div>
          <p className="mt-2 leading-6">{error}</p>
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {isLoading
          ? Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="min-h-72 animate-pulse rounded-[1.5rem] border border-white/10 bg-white/[0.055] p-5"
              >
                <div className="h-8 w-36 rounded-lg bg-white/10" />
                <div className="mt-5 h-20 rounded-lg bg-white/10" />
                <div className="mt-8 h-16 rounded-lg bg-black/20" />
              </div>
            ))
          : projects.map((project) => (
              <Link
                key={project.key}
                href={`/projects/${project.key}`}
                className="group flex min-h-72 flex-col justify-between rounded-[1.5rem] border border-white/10 bg-white/[0.055] p-5 shadow-card backdrop-blur-2xl transition hover:border-moss/35 hover:bg-white/[0.075]"
              >
                <div>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-white/[0.07] text-moss">
                      <FolderKanban className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <span className={`rounded-full border px-3 py-1 text-xs font-medium ${statusClass(project.status)}`}>
                      {project.status}
                    </span>
                  </div>
                  <h4 className="mt-7 text-2xl font-semibold text-pearl">{project.name}</h4>
                  <p className="mt-3 text-sm leading-6 text-stone-400">{project.description}</p>
                </div>

                <div className="mt-8 space-y-4">
                  <div className="rounded-2xl bg-black/20 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Next move</p>
                    <p className="mt-2 line-clamp-2 text-sm font-medium leading-5 text-pearl">
                      {project.next_recommendation}
                    </p>
                  </div>
                  <div className="flex items-center justify-between gap-3 text-xs text-stone-500">
                    <span className="flex items-center gap-1.5">
                      <ListTodo className="h-3.5 w-3.5" aria-hidden="true" />
                      {projectMetricLabel(project)}
                    </span>
                    <span className="flex items-center gap-1.5 text-stone-400 transition group-hover:text-moss">
                      Open
                      <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </span>
                  </div>
                </div>
              </Link>
            ))}
      </section>

      {!isLoading && !error && projects.length === 0 ? (
        <div className="rounded-[1.4rem] border border-white/10 bg-white/[0.045] p-5 text-sm text-stone-400">
          <CheckCircle2 className="mb-3 h-5 w-5 text-moss" aria-hidden="true" />
          No project data yet.
        </div>
      ) : null}

      {!isLoading && !error ? (
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Live from Todoist, Calendar, Memory, and Activity
          <CalendarClock className="ml-2 h-3.5 w-3.5" aria-hidden="true" />
        </div>
      ) : null}
    </div>
  );
}
