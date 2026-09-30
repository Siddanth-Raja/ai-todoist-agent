"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Activity, ArrowRight, CalendarClock, CheckCircle2, Clock3, ExternalLink, MessageCircle, PenLine } from "lucide-react";
import { formatDateTime, type ActivityEntry, type CollegeBriefProjection, type LifeArea, type TodayResponse } from "@/lib/api";
import { todayMustDoItemLabel, todayMustDoPresentation, todayProjectCardPresentation } from "@/lib/today-projection-presentation";
import { useRetainedApiQuery } from "@/lib/use-retained-api-query";
import { RealityEvidenceCard, RealityEvidenceDisclosure } from "@/components/reality-evidence";
import { CollegeReview } from "@/components/college-review";

import { syntheticRuntime } from "@/lib/runtime-session";

const projectHrefByLifeArea: Record<string, string> = { "A&M": "/projects/am", XO: "/projects/xo", Nebulo: "/projects/nebulo", Freelance: "/projects/freelance", Personal: "/projects/personal" };
function getGreeting(hour: number) { return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening"; }
function formatActionType(value: string) { return value.replaceAll("_", " "); }
function iconForActivity(_value: string) { return Activity; }
function formatObligationDate(value: string) { return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(`${value}T12:00:00`)); }
function openCapture(checkSaved = false) {
  if (checkSaved) { const heading = document.getElementById("college-review-heading"); heading?.scrollIntoView({ block: "start" }); heading?.focus(); return; }
  const capture = document.querySelector<HTMLDetailsElement>(".college-capture");
  if (capture) { capture.open = true; capture.scrollIntoView({ block: "start" }); capture.querySelector("summary")?.focus(); }
}
function PanelTitle({ title, href, label = "View all" }: { title: string; href?: string; label?: string }) {
  return <div className="daily-panel-title"><h2>{title}</h2>{href ? <Link href={href}>{label}<ArrowRight size={14} aria-hidden="true" /></Link> : null}</div>;
}

export default function TodayPage() {
  const [hasPendingUpdate, setHasPendingUpdate] = useState(false);
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [collegeStale, setCollegeStale] = useState(false);
  const todayQuery = useRetainedApiQuery<TodayResponse>("/today");
  const activityQuery = useRetainedApiQuery<ActivityEntry[]>("/activity?limit=5");
  const todayData = todayQuery.data;
  const lifeAreas: LifeArea[] = todayData?.life_areas ?? [];
  const lifeAreaWarnings = todayData?.errors ?? [];
  const lifeAreaError = todayQuery.initialError ?? todayQuery.refreshError;
  const activityEntries = activityQuery.data ?? [];
  const activityError = activityQuery.initialError ?? activityQuery.refreshError;
  const isLifeAreasLoading = todayQuery.isInitialLoading;

  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 30000);

    return () => window.clearInterval(timer);
  }, []);

  const hour = now.getHours();
  const greeting = getGreeting(hour);

  const currentBlock = todayData?.current_free_block ?? null;
  const commitments = todayData?.today_remaining_events ?? [];

  const mustDo = todayData?.must_do ?? null;
  const mustDoPresentation = mustDo ? todayMustDoPresentation(mustDo) : null;
  const recommendation = todayData?.recommendation ?? null;
  const collegeEvidence = recommendation?.evidence.find(
    (item) => item.signal === "college_attention_projection",
  );
  const college = (
    collegeEvidence?.value &&
    typeof collegeEvidence.value === "object" &&
    (collegeEvidence.value as { schema_version?: string }).schema_version === "college-brief/1.0"
      ? collegeEvidence.value as CollegeBriefProjection
      : null
  );
  async function refreshAfterCollegeChange() {
    try {
      await todayQuery.refresh();
      setCollegeStale(false);
    } catch {
      setCollegeStale(true);
      // Keep the prior College judgment hidden until a successful read.
    }
  }
  const isTodayLoading = !todayData && isLifeAreasLoading;
  const isTodayUnavailable = !todayData && !isLifeAreasLoading;
  const recentActivity = useMemo(
    () =>
      activityEntries.map((entry) => ({
        id: entry.id,
        label: formatActionType(entry.type || entry.action_type),
        value: entry.title,
        detail: [entry.source, entry.description || entry.detail || formatDateTime(entry.created_at)]
          .filter(Boolean)
          .join(" - "),
        icon: iconForActivity(entry.type || entry.action_type),
      })),
    [activityEntries],
  );

  if (collegeStale && college) {
    return <div className="mx-auto w-full max-w-4xl space-y-4 px-4 pb-12">
      <h1 className="text-2xl font-semibold text-pearl">Today needs refresh</h1>
      <p className="text-sm leading-6 text-stone-300">College state changed. The prior judgment is hidden until a fresh read succeeds.</p>
      <button type="button" onClick={() => void refreshAfterCollegeChange()} className="min-h-11 rounded-xl border border-white/15 px-4 text-stone-200">Retry Today refresh</button>
      <CollegeReview brief={college} briefStale onChange={refreshAfterCollegeChange} />
    </div>;
  }

  return (
    <div className="today-view daily-dashboard">
      <section className="today-lead daily-lead">
        <p className="daily-date" suppressHydrationWarning>{todayData?.now_display ?? now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
        <p className="daily-greeting" suppressHydrationWarning>{greeting}, {syntheticRuntime ? "synthetic owner" : "Siddanth"}.</p>
        <h1>{recommendation?.title ?? (isTodayUnavailable ? "Today is unavailable" : "Reading your day…")}</h1>
        <p className="daily-recommendation">{recommendation?.detail ?? (isTodayUnavailable ? "Connect your backend in Settings to see your day." : "Checking your calendar and work.")}</p>
        {recommendation?.reality ? <RealityEvidenceDisclosure item={recommendation.reality} /> : null}
        {lifeAreaError ? <p role="status" className="daily-warning">{todayData ? "Today refresh failed; showing retained state. " : "Today unavailable. "}{lifeAreaError}</p> : null}
        {lifeAreaWarnings.length ? <details className="daily-limits"><summary>Some sources need attention</summary><p>{lifeAreaWarnings.join(" ")}</p></details> : null}
      </section>

      <div className="daily-actions">
        <Link href="/tasks"><CheckCircle2 aria-hidden="true" />Tasks</Link>
        <Link href="/calendar"><CalendarClock aria-hidden="true" />Calendar</Link>
        <Link href="/chat"><MessageCircle aria-hidden="true" />Open Chat</Link>
        {college ? <button type="button" onClick={() => openCapture(hasPendingUpdate)}><PenLine aria-hidden="true" />Class update</button> : null}
      </div>

      <section className="daily-panel daily-timeline" aria-label="Remaining calendar commitments">
        <div className="daily-timeline-heading"><PanelTitle title="Next up" href="/calendar" label="Calendar" />{commitments.length > 1 ? <button className="timeline-toggle" type="button" aria-expanded={timelineExpanded} aria-controls="daily-timeline-events" onClick={() => setTimelineExpanded(!timelineExpanded)}>{timelineExpanded ? "Show next" : `All ${commitments.length}`}<ArrowRight size={14} aria-hidden="true" /></button> : null}</div>
        {commitments.length ? <ol id="daily-timeline-events" className={`daily-timeline-list ${timelineExpanded ? "expanded" : ""}`}>{commitments.map((event) => <li key={event.id ?? `${event.title}-${event.start}`}>
          <time dateTime={event.start}>{event.start_display}</time><span className="timeline-dot" aria-hidden="true" />
          <div className="timeline-event"><div><h3>{event.title}</h3><p>{event.location || event.event_category.replaceAll("_", " ")}</p></div><span className="daily-duration">{event.duration_minutes}m</span>
          {event.html_link ? <a href={event.html_link} target="_blank" rel="noreferrer" aria-label={`Open ${event.title} in Calendar`}><ExternalLink size={14} aria-hidden="true" /></a> : null}</div>
        </li>)}</ol> : <p className="daily-empty">{isTodayLoading ? "Reading Calendar…" : isTodayUnavailable || syntheticRuntime ? "Calendar unavailable. No clear schedule is implied." : "No remaining commitments are recorded."}</p>}
        {currentBlock ? <p className="daily-free"><Clock3 size={14} aria-hidden="true" />{currentBlock.duration_minutes} min open now{currentBlock.low_usefulness ? " · short usable window" : ""}</p> : null}
      </section>

      <section className="daily-panel daily-attention" aria-label="Needs attention">
        <PanelTitle title="Needs attention" href="/tasks" label="Tasks" />
        {/* Must do remains distinct from College reports; neither is reranked in the client. */}
        <div aria-label="Must do" className="daily-obligations">
          {mustDoPresentation?.warning ? <p className="daily-warning">{mustDoPresentation.warning}</p> : null}
          {mustDo?.items.length ? mustDo.items.map((obligation) => <article className="daily-attention-row" key={`${obligation.provider}:${obligation.provider_record_id}`}>
            <span className="daily-dot due" aria-hidden="true" /><div className="daily-row-content"><h3>{obligation.title}</h3><p>{todayMustDoItemLabel(obligation)} · {formatObligationDate(obligation.due_date)}</p>
            {obligation.reality ? <RealityEvidenceDisclosure item={obligation.reality} /> : null}</div>
            {obligation.provider_url ? <a className="daily-source" href={obligation.provider_url} target="_blank" rel="noreferrer" aria-label={`Open ${obligation.title} in ${obligation.provider}`}>{obligation.provider}<ExternalLink size={12} aria-hidden="true" /></a> : <span className="daily-tag">{obligation.provider}</span>}
          </article>) : <p className="daily-empty">{isTodayLoading ? "Reading obligations…" : isTodayUnavailable ? "Obligations unavailable." : mustDoPresentation?.emptyTitle ?? "No current obligation read is available."}</p>}
        </div>
        {college ? <div className="daily-college-attention">
          <p className="daily-section-label">College · {college.assessment_status === "ready" ? "recorded assessment" : college.assessment_status.replaceAll("_", " ")}</p>
          <p className="daily-college-opening">{college.opening}</p>
          {college.decisive_items.length > 1 ? <ul>{college.decisive_items.slice(1).map((item) => <li className="daily-attention-row" key={`${item.subject_id}:${item.source_order}`}><span className="daily-dot" aria-hidden="true" /><div className="daily-row-content"><p>{item.summary}</p><small>{item.certainty.replaceAll("_", " ")}</small></div></li>)}</ul> : null}
          <details className="daily-limits"><summary>Scope and sources{college.complete_for_scope ? "" : " · limited coverage"}</summary>
            <p>{college.scope_label}. This College assessment does not describe the rest of your day.</p>
            {college.coverage_gaps.map((gap) => <p key={`${gap.provider}:${gap.account_id ?? "default"}`}>{gap.provider}: {gap.availability}, {gap.completeness} coverage, {gap.freshness} freshness. {gap.reason.replaceAll("_", " ")}.{gap.provider.toLowerCase() === "blinn" ? " Blinn remains pending; its mailbox has not been checked here." : ""}</p>)}
            {college.evidence_refs.length ? <details><summary>Technical references</summary><p className="break-all">{college.evidence_refs.join(" · ")}</p></details> : null}
          </details>
        </div> : null}
      </section>

      <section className="daily-panel daily-upcoming" aria-label="Upcoming College context">
        <PanelTitle title="Coming up" />
        {college?.session_changes.length ? <ul className="daily-context-list">{college.session_changes.map((item) => <li key={`${item.subject_id}:${item.source_order}`}><span className="daily-dot" aria-hidden="true" /><div><h3>{item.subject_label}</h3><p>{item.summary}</p></div></li>)}</ul> : <p className="daily-empty">{college ? "No class changes are recorded." : "Class context is unavailable."}</p>}
        {college ? <div className="daily-wait"><h3>Can wait</h3>{college.safe_to_wait.length ? <ul>{college.safe_to_wait.map((item) => <li key={`${item.subject_id}:${item.source_order}`}>{item.summary}</li>)}</ul> : <p>Nothing is confirmed safe to put off.</p>}</div> : null}
      </section>

      <section className="daily-panel daily-projects" aria-label="Projects">
        <PanelTitle title="Projects" href="/projects" />
        {lifeAreas.length ? <div>{lifeAreas.map((area) => { const projection = todayProjectCardPresentation(area); return <Link className="daily-project-row" key={area.name} href={projectHrefByLifeArea[area.name] ?? "/projects"}>
          <span className="daily-dot project" aria-hidden="true" /><div className="daily-row-content"><h3>{area.name}</h3><p>{projection.nextMove || area.description}</p>{projection.failure ? <p className="daily-warning">{projection.failure}</p> : null}</div>
          <span className="daily-project-meta">{area.task_count} tasks<small>{projection.status}</small></span><ArrowRight size={14} aria-hidden="true" />
        </Link>; })}</div> : <p className="daily-empty">{isTodayLoading ? "Reading projects…" : isTodayUnavailable ? "Projects unavailable." : "No projects are available in this view."}</p>}
      </section>

      <section className="daily-panel daily-activity" aria-label="Recent updates">
        <PanelTitle title="Recent updates" />
        {activityError ? <p role="status" className="daily-warning">{activityError}</p> : null}
        {recentActivity.length ? recentActivity.map((item) => <article className="daily-activity-row" key={item.id}><Activity size={16} aria-hidden="true" /><div><h3>{item.value}</h3><p>{item.detail}</p></div></article>) : <p className="daily-empty">{activityQuery.isInitialLoading ? "Reading updates…" : activityError ? "Updates unavailable." : "No activity recorded yet."}</p>}
      </section>

      {todayData?.reality_attention.length ? <section className="daily-panel daily-wide"><PanelTitle title="Details to reconcile" /><p className="daily-empty">Review these differences before changing an outside account.</p>{todayData.reality_attention.map((item) => <RealityEvidenceCard key={item.reality_item_id} item={item} />)}</section> : null}
      {college ? <div className="daily-review"><CollegeReview brief={college} showContext={false} onPendingChange={setHasPendingUpdate} onChange={refreshAfterCollegeChange} /></div> : null}
      {college ? <div className="daily-capture-dock"><button type="button" onClick={() => openCapture(hasPendingUpdate)}><PenLine size={18} aria-hidden="true" /><span>{hasPendingUpdate ? "Check your saved update" : "Share a class update…"}</span><span className="capture-arrow"><ArrowRight size={18} aria-hidden="true" /></span></button></div> : null}
    </div>
  );
}
