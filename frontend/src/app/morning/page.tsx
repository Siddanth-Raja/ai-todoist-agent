"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ChevronDown,
  CircleAlert,
  History,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  SunMedium,
  Undo2,
  X,
} from "lucide-react";

import {
  apiRequest,
  formatDateTime,
  type MorningCorrection,
  type MorningCorrectionType,
  type MorningSection,
  type MorningStateSynthesis,
  type MorningStatement,
  type ProviderMutationPreview,
} from "@/lib/api";
import {
  applicableCorrections,
  correctionLabel,
  correctionOutcome,
  correctionRequestPayload,
  MORNING_SECTION_COPY,
  providerConfirmationPayload,
  providerPreviewPayload,
  statementPresentation,
} from "@/lib/morning-brief";
import { useRetainedApiQuery } from "@/lib/use-retained-api-query";


function requestIdentity(prefix: string) {
  return `${prefix}:${crypto.randomUUID()}`;
}

function safeValue(value: unknown) {
  if (typeof value === "string") return value;
  if (value === null || typeof value === "undefined") return "Unavailable";
  return JSON.stringify(value);
}

function correctionStateLabel(record: MorningCorrection) {
  const boundary = record.review_at ?? record.expires_at;
  return `${correctionLabel(record.correction_type)} · ${record.status}${
    boundary ? ` · review ${formatDateTime(boundary)}` : ""
  }`;
}

function EvidenceDetails({ statement }: { statement: MorningStatement }) {
  const identities = statement.provider_identities;
  return (
    <div className="space-y-4 text-sm leading-6 text-stone-400">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500">Evidence</p>
        <dl className="grid gap-3 rounded-xl border border-white/10 bg-white/[0.025] p-3 sm:grid-cols-3">
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-stone-500">Confidence</dt>
            <dd className="mt-1 capitalize text-stone-200">{statement.confidence}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-stone-500">Freshness</dt>
            <dd className="mt-1 capitalize text-stone-200">{statement.freshness}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-stone-500">Provider coverage</dt>
            <dd className="mt-1 capitalize text-stone-200">{statement.availability.replaceAll("_", " ")}</dd>
          </div>
        </dl>

        {statement.source_evidence_summaries.length ? (
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Supporting evidence</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {statement.source_evidence_summaries.map((summary) => <li key={summary}>{summary}</li>)}
            </ul>
          </div>
        ) : <p>{statement.reason}</p>}

        {statement.suggested_action ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
            <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Reviewable next step</p>
            <p className="mt-1 text-stone-200">{statement.suggested_action.summary}</p>
            <p className="mt-1 text-xs text-stone-500">Requires confirmation and does not change an external provider.</p>
          </div>
        ) : null}

        {statement.source_timestamps.length ? (
          <p>
            <span className="text-stone-200">Observed:</span>{" "}
            {statement.source_timestamps.map(formatDateTime).join(" · ")}
          </p>
        ) : null}
        {statement.uncertainty.length ? (
          <div className="rounded-xl border border-iris/20 bg-iris/[0.06] px-3 py-2 text-stone-300">
            <span className="font-medium text-iris">Uncertainty:</span> {statement.uncertainty.join(" ")}
          </div>
        ) : null}

        <details className="rounded-xl border border-white/10 bg-black/15">
          <summary className="min-h-11 cursor-pointer px-3 py-3 text-xs font-medium text-stone-500">Technical source references</summary>
          <div className="space-y-3 border-t border-white/10 p-3 text-xs">
            <p>Classification: {statement.classification.replaceAll("_", " ")} · Evidence type: {statement.fact_type.replaceAll("_", " ")}</p>
            {identities.length ? (
              <ul className="space-y-2">
                {identities.map((identity) => (
                  <li key={`${identity.provider}:${identity.provider_record_type}:${identity.provider_record_id}`} className="break-words">
                    {identity.provider} · {identity.provider_record_type} · {identity.provider_record_id}
                    {identity.provider_url ? (
                      <a className="ml-2 inline-flex items-center gap-1 text-moss hover:text-pearl" href={identity.provider_url} target="_blank" rel="noreferrer">
                        Open source <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
            {statement.temporal ? (
              <p>{Object.entries(statement.temporal).filter(([, value]) => value !== null).map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`).join(" · ") || "No explicit time boundary"}</p>
            ) : null}
            <p className="break-words">Evidence references: {statement.source_evidence_references.join(" · ")}</p>
          </div>
        </details>
      </div>
    </div>
  );
}

function CorrectionHistory({
  records,
  loading,
  onLoad,
  onUndo,
  pending,
  title = "Correction history",
  embedded = false,
}: {
  records: MorningCorrection[] | undefined;
  loading: boolean;
  onLoad: () => void;
  onUndo: (record: MorningCorrection) => void;
  pending: boolean;
  title?: string;
  embedded?: boolean;
}) {
  const content = (
    <div className={embedded ? "text-sm text-stone-400" : "border-t border-white/10 px-4 py-4 text-sm text-stone-400"}>
      {embedded ? <p className="mb-3 inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-stone-500"><History className="h-4 w-4" aria-hidden="true" />{title}</p> : null}
        {loading ? <p>Loading correction history…</p> : null}
        {!loading && records?.length === 0 ? <p>No correction has been recorded for this statement.</p> : null}
        {records?.length ? (
          <ul className="space-y-3">
            {records.map((record) => (
              <li key={record.correction_id} className="rounded-xl border border-white/10 bg-white/[0.025] p-3">
                <p className="font-medium text-stone-200">{correctionStateLabel(record)}</p>
                <p className="mt-1 text-xs">By {record.correcting_actor} · {formatDateTime(record.created_at)}</p>
                {record.status === "active" ? (
                  <button
                    type="button"
                    disabled={pending}
                    onClick={() => onUndo(record)}
                    className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-stone-200 hover:bg-white/[0.06] disabled:opacity-50"
                  >
                    <Undo2 className="h-4 w-4" aria-hidden="true" /> Undo PCOS correction
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
    </div>
  );
  if (embedded) return content;
  return (
    <details
      className="rounded-2xl border border-white/10 bg-black/15"
      onToggle={(event) => event.currentTarget.open && onLoad()}
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-stone-300">
        <span className="inline-flex items-center gap-2"><History className="h-4 w-4" aria-hidden="true" />{title}</span>
        <ChevronDown className="h-4 w-4 transition group-open:rotate-180" aria-hidden="true" />
      </summary>
      {content}
    </details>
  );
}

function StatementCard({
  statement,
  onCorrection,
  onProviderPreview,
  history,
  historyLoading,
  loadHistory,
  undoCorrection,
  pending,
  compact = false,
  forceReview = false,
  displaySummary,
}: {
  statement: MorningStatement;
  onCorrection: (statement: MorningStatement, type: MorningCorrectionType) => void;
  onProviderPreview: (statement: MorningStatement, trigger: HTMLButtonElement) => void;
  history: MorningCorrection[] | undefined;
  historyLoading: boolean;
  loadHistory: () => void;
  undoCorrection: (record: MorningCorrection) => void;
  pending: boolean;
  compact?: boolean;
  forceReview?: boolean;
  displaySummary?: string;
}) {
  const canonicalPresentation = statementPresentation(statement);
  const presentation = forceReview ? {
    label: "Review first",
    tone: "border-gold/30 bg-gold/[0.07]",
    badge: "bg-gold/15 text-gold",
    priority: "review",
  } as const : canonicalPresentation;
  const corrections = applicableCorrections(statement);
  return (
    <article
      className={`rounded-[1.6rem] border p-4 ${compact ? "" : "shadow-card sm:p-5"} ${presentation.tone}`}
      data-attention-priority={presentation.priority}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${presentation.badge}`}>{presentation.label}</span>
          </div>
          <h3 className={`${compact ? "text-base" : "text-lg sm:text-xl"} mt-3 font-semibold leading-7 text-pearl`}>{displaySummary ?? statement.summary}</h3>
        </div>
      </div>

      <details
        className="group mt-4 rounded-2xl border border-white/10 bg-black/15"
        onToggle={(event) => event.currentTarget.open && statement.source_reconciliation_id && loadHistory()}
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-stone-300">
          Details and corrections
          <ChevronDown className="h-4 w-4 transition group-open:rotate-180" aria-hidden="true" />
        </summary>
        <div className="space-y-5 border-t border-white/10 p-4">
          <EvidenceDetails statement={statement} />
          {corrections.length ? (
            <div>
              <p className="mb-3 text-xs font-medium uppercase tracking-[0.18em] text-stone-500">Corrections</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {corrections.map((type) => (
                  <div key={type} className="rounded-xl border border-white/10 bg-white/[0.025] p-3">
                    <p className="font-medium text-stone-200">{correctionLabel(type)}</p>
                    <p className="mt-1 text-xs leading-5 text-stone-400">{correctionOutcome(type)}</p>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() => onCorrection(statement, type)}
                      className="mt-3 min-h-11 rounded-xl bg-pearl px-4 text-sm font-medium text-ink hover:bg-white disabled:opacity-50"
                    >
                      Record {correctionLabel(type)}
                    </button>
                  </div>
                ))}
                {statement.linked_work_identity ? (
                  <div className="rounded-xl border border-gold/20 bg-gold/[0.045] p-3">
                    <p className="font-medium text-stone-200">Mark complete in {statement.linked_work_identity.provider}</p>
                    <p className="mt-1 text-xs leading-5 text-stone-400">This is different from a PCOS correction. The first step only previews one exact provider record and field; it cannot mutate anything.</p>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={(event) => onProviderPreview(statement, event.currentTarget)}
                      className="mt-3 min-h-11 rounded-xl border border-gold/30 px-4 text-sm font-medium text-gold hover:bg-gold/10 disabled:opacity-50"
                    >
                      Preview exact provider change
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          {statement.source_reconciliation_id ? (
            <CorrectionHistory
              records={history}
              loading={historyLoading}
              onLoad={loadHistory}
              onUndo={undoCorrection}
              pending={pending}
              embedded
            />
          ) : null}
        </div>
      </details>
    </article>
  );
}

function SectionHeading({
  section,
  index,
  countLabel,
}: {
  section: MorningSection;
  index: number;
  countLabel?: string;
}) {
  const copy = MORNING_SECTION_COPY[section.section_id];
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">{copy.eyebrow}</p>
        <h2 id={`morning-section-${index}`} className="mt-2 text-2xl font-semibold text-pearl sm:text-3xl">{section.heading}</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-400">{copy.detail}</p>
      </div>
      <p className="text-xs text-stone-500">{countLabel ?? `${section.returned_count} of ${section.total_count}${section.truncated ? " shown" : ""}`}</p>
    </div>
  );
}

function ControlCount({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
      <p className="text-2xl font-semibold text-pearl">{value}</p>
      <p className="mt-1 text-sm text-stone-400">{label}</p>
    </div>
  );
}

function ProviderDialog({
  open,
  preview,
  loading,
  error,
  confirming,
  close,
  confirm,
}: {
  open: boolean;
  preview: ProviderMutationPreview | null;
  loading: boolean;
  error: string | null;
  confirming: boolean;
  close: () => void;
  confirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input:not([disabled])",
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [close, open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="provider-dialog-title"
        className="max-h-[calc(100dvh-2rem)] w-full max-w-xl overflow-y-auto rounded-[2rem] border border-white/15 bg-[#111113] p-5 shadow-soft sm:p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-gold">External provider</p>
            <h2 id="provider-dialog-title" className="mt-2 text-2xl font-semibold text-pearl">Exact completion preview</h2>
          </div>
          <button ref={closeRef} type="button" aria-label="Close provider preview" onClick={close} className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 text-stone-300 hover:bg-white/[0.06]">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        {loading ? <p className="mt-6 text-stone-300">Reading the exact provider target. No mutation is occurring…</p> : null}
        {error ? <p role="alert" className="mt-6 rounded-xl border border-coral/30 bg-coral/10 p-3 text-sm text-coral">{error}</p> : null}
        {preview ? (
          <div className="mt-6 space-y-4">
            <dl className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.035] p-4 text-sm sm:grid-cols-2">
              <div><dt className="text-stone-500">Provider</dt><dd className="mt-1 break-words text-stone-200">{preview.provider}</dd></div>
              <div><dt className="text-stone-500">Record</dt><dd className="mt-1 break-words text-stone-200">{preview.provider_record_type} · {preview.provider_record_id}</dd></div>
              <div><dt className="text-stone-500">Field</dt><dd className="mt-1 text-stone-200">{preview.field_name}</dd></div>
              <div className="min-w-0"><dt className="text-stone-500">Evidence version</dt><dd className="mt-1 break-all text-stone-200">{preview.evidence_version}</dd></div>
              <div><dt className="text-stone-500">Previous value</dt><dd className="mt-1 break-words text-stone-200">{safeValue(preview.previous_value)}</dd></div>
              <div><dt className="text-stone-500">Proposed value</dt><dd className="mt-1 break-words text-stone-200">{safeValue(preview.proposed_value)}</dd></div>
            </dl>
            {preview.diagnostic ? <p className="rounded-xl border border-gold/25 bg-gold/[0.07] p-3 text-sm leading-6 text-stone-300">{preview.diagnostic}</p> : null}
            {preview.status === "ready" ? (
              <>
                <p className="text-sm leading-6 text-stone-400">Confirmation is bound to every field above. The backend will re-read the target; any changed value or revision invalidates this preview.</p>
                <button type="button" disabled={confirming} onClick={confirm} className="min-h-12 w-full rounded-xl bg-gold px-4 font-medium text-ink hover:bg-amber-200 disabled:opacity-50">
                  {confirming ? "Revalidating exact target…" : "Confirm this exact provider change"}
                </button>
              </>
            ) : null}
            {preview.status === "succeeded" ? <p role="status" className="rounded-xl border border-moss/25 bg-moss/10 p-3 text-sm text-moss">Provider completion was verified successfully.</p> : null}
            {preview.status === "stale" ? <p role="alert" className="rounded-xl border border-gold/25 bg-gold/10 p-3 text-sm text-gold">Provider state changed or the preview expired. Close this dialog and request a new preview.</p> : null}
            {preview.status === "failed" || preview.status === "uncertain" ? <p role="alert" className="rounded-xl border border-coral/25 bg-coral/10 p-3 text-sm text-coral">The provider change is not confirmed. {preview.diagnostic}</p> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function MorningPage() {
  const query = useRetainedApiQuery<MorningStateSynthesis>("/morning-state");
  const synthesis = query.data;
  const [pending, setPending] = useState(false);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [history, setHistory] = useState<Record<string, MorningCorrection[]>>({});
  const [historyLoading, setHistoryLoading] = useState<string | null>(null);
  const [ledger, setLedger] = useState<MorningCorrection[] | undefined>();
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [preview, setPreview] = useState<ProviderMutationPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const previewTrigger = useRef<HTMLButtonElement | null>(null);

  const closeDialog = () => {
    setDialogOpen(false);
    window.setTimeout(() => previewTrigger.current?.focus(), 0);
  };

  async function loadHistory(statementId: string) {
    if (history[statementId] || historyLoading === statementId) return;
    setHistoryLoading(statementId);
    try {
      const records = await apiRequest<MorningCorrection[]>(`/morning-corrections?statement_id=${encodeURIComponent(statementId)}`);
      setHistory((value) => ({ ...value, [statementId]: records }));
    } catch (error) {
      setAnnouncement(error instanceof Error ? error.message : "Correction history failed to load.");
    } finally {
      setHistoryLoading(null);
    }
  }

  async function loadLedger() {
    if (ledger || ledgerLoading) return;
    setLedgerLoading(true);
    try {
      setLedger(await apiRequest<MorningCorrection[]>("/morning-corrections"));
    } catch (error) {
      setAnnouncement(error instanceof Error ? error.message : "Correction ledger failed to load.");
    } finally {
      setLedgerLoading(false);
    }
  }

  async function applyCorrection(statement: MorningStatement, type: MorningCorrectionType) {
    if (!synthesis || pending) return;
    setPending(true);
    setAnnouncement(`Recording ${correctionLabel(type)} as PCOS-owned state…`);
    try {
      await apiRequest<MorningCorrection>("/morning-corrections", {
        method: "POST",
        body: JSON.stringify(correctionRequestPayload(synthesis, statement, type, requestIdentity("morning-correction"))),
      });
      setHistory((value) => {
        const next = { ...value };
        delete next[statement.statement_id];
        return next;
      });
      setLedger(undefined);
      setAnnouncement(`${correctionLabel(type)} was recorded in PCOS. No provider data was changed.`);
      await query.refresh();
    } catch (error) {
      setAnnouncement(error instanceof Error ? error.message : "Correction failed.");
    } finally {
      setPending(false);
    }
  }

  async function undoCorrection(record: MorningCorrection) {
    if (pending) return;
    setPending(true);
    try {
      await apiRequest<MorningCorrection>(`/morning-corrections/${record.correction_id}/undo`, {
        method: "POST",
        body: JSON.stringify({ reversing_actor: "user-primary", idempotency_key: requestIdentity("morning-undo") }),
      });
      setHistory((value) => {
        const next = { ...value };
        delete next[record.statement_id];
        return next;
      });
      setLedger(undefined);
      setAnnouncement("The reversible PCOS correction was undone. Provider data was not changed.");
      await query.refresh();
    } catch (error) {
      setAnnouncement(error instanceof Error ? error.message : "Undo failed.");
    } finally {
      setPending(false);
    }
  }

  async function openProviderPreview(statement: MorningStatement, trigger: HTMLButtonElement) {
    if (!synthesis || pending || previewLoading) return;
    setPending(true);
    previewTrigger.current = trigger;
    setDialogOpen(true);
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const result = await apiRequest<ProviderMutationPreview>("/morning-provider-reconciliation/preview", {
        method: "POST",
        body: JSON.stringify(providerPreviewPayload(synthesis, statement, requestIdentity("morning-provider-preview"))),
      });
      setPreview(result);
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "Provider preview failed.");
    } finally {
      setPreviewLoading(false);
      setPending(false);
    }
  }

  async function confirmProviderChange() {
    if (!preview || preview.status !== "ready" || confirming) return;
    setConfirming(true);
    try {
      const result = await apiRequest<ProviderMutationPreview>("/morning-provider-reconciliation/confirm", {
        method: "POST",
        body: JSON.stringify(providerConfirmationPayload(preview, requestIdentity("morning-provider-confirm"))),
      });
      setPreview(result);
      setAnnouncement(result.status === "succeeded" ? "The exact provider completion was verified." : "The provider completion was not confirmed; review the dialog state.");
      if (result.status === "succeeded") await query.refresh();
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "Provider confirmation failed.");
    } finally {
      setConfirming(false);
    }
  }

  if (!synthesis && query.isInitialLoading) {
    return <div className="mx-auto flex min-h-[55vh] max-w-4xl items-center justify-center px-4 text-stone-400">Preparing an evidence-backed morning brief…</div>;
  }
  if (!synthesis) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <div className="rounded-[2rem] border border-coral/25 bg-coral/[0.07] p-6">
          <h1 className="text-2xl font-semibold text-pearl">The Morning Brief is unavailable</h1>
          <p className="mt-3 text-stone-300">{query.initialError ?? "No retained brief is available yet."}</p>
          <button type="button" onClick={() => void query.refresh()} className="mt-5 min-h-11 rounded-xl bg-pearl px-4 font-medium text-ink">Try again</button>
        </div>
      </div>
    );
  }

  const primaryStatement = synthesis.attention_today.statements.find(
    (item) => item.statement_id === synthesis.briefing.primary_statement_id,
  );
  const materialChangeIds = new Set(synthesis.briefing.material_change_statement_ids);
  const materialChanges = synthesis.changes_since_meaningful_check.statements.filter(
    (item) => materialChangeIds.has(item.statement_id),
  );
  const supportIds = new Set(synthesis.briefing.support_statement_ids);
  const supportHighlights = synthesis.handled_paused_waiting.statements.filter(
    (item) => supportIds.has(item.statement_id),
  );
  const remainingAttention = synthesis.attention_today.statements.filter(
    (item) => item.statement_id !== synthesis.briefing.primary_statement_id,
  );
  const remainingSupport = synthesis.handled_paused_waiting.statements.filter(
    (item) => !supportIds.has(item.statement_id),
  );

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-3 pb-12 sm:px-4 md:px-6">
      <section className="overflow-hidden rounded-[2.2rem] border border-white/12 bg-gradient-to-br from-moss/[0.13] via-white/[0.055] to-iris/[0.09] p-5 shadow-soft sm:p-7 md:p-9">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-pearl text-ink shadow-card"><SunMedium className="h-5 w-5" aria-hidden="true" /></div>
            <p className="mt-6 text-xs font-medium uppercase tracking-[0.28em] text-moss">Today&apos;s brief</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-pearl sm:text-4xl md:text-5xl">{synthesis.briefing.headline}</h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-stone-300">{synthesis.briefing.summary}</p>
          </div>
          <div className="flex flex-wrap gap-2 md:max-w-xs md:justify-end">
            <span className="rounded-full border border-white/10 bg-black/20 px-3 py-2 text-xs text-stone-300">Evaluated {formatDateTime(synthesis.evaluated_at)}</span>
            <button type="button" disabled={query.isRefreshing} onClick={() => void query.refresh()} className="inline-flex min-h-11 items-center gap-2 rounded-full border border-white/10 bg-black/20 px-4 text-sm text-stone-200 hover:bg-white/[0.06] disabled:opacity-50">
              <RefreshCw className={`h-4 w-4 ${query.isRefreshing ? "animate-spin" : ""}`} aria-hidden="true" /> Refresh
            </button>
          </div>
        </div>
        {primaryStatement ? (
          <div className="mt-7">
            <p className={`mb-3 text-xs font-medium uppercase tracking-[0.24em] ${synthesis.briefing.primary_kind === "move" ? "text-coral" : "text-gold"}`}>
              {synthesis.briefing.primary_kind === "move" ? "Primary move" : "Review before acting"}
            </p>
            <StatementCard
              statement={primaryStatement}
              onCorrection={applyCorrection}
              onProviderPreview={openProviderPreview}
              history={history[primaryStatement.statement_id]}
              historyLoading={historyLoading === primaryStatement.statement_id}
              loadHistory={() => void loadHistory(primaryStatement.statement_id)}
              undoCorrection={undoCorrection}
              pending={pending}
              forceReview={synthesis.briefing.primary_kind === "review"}
              displaySummary={synthesis.briefing.primary_caution ?? undefined}
            />
          </div>
        ) : synthesis.no_urgent_attention ? (
          <div className="mt-7 flex items-start gap-3 rounded-2xl border border-moss/25 bg-moss/[0.09] p-4 text-moss">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <div><p className="font-medium">Nothing urgent needs attention.</p><p className="mt-1 text-sm leading-6 text-stone-300">Complete eligible evidence supports this calm state. Project context and the shape of today remain below.</p></div>
          </div>
        ) : !synthesis.complete_evidence ? (
          <div className="mt-7 flex items-start gap-3 rounded-2xl border border-iris/25 bg-iris/[0.08] p-4">
            <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-iris" aria-hidden="true" />
            <div><p className="font-medium text-pearl">Some evidence is incomplete.</p><p className="mt-1 text-sm leading-6 text-stone-300">Usable portions remain visible. Absence of an urgent item is not being treated as proof that everything is handled.</p></div>
          </div>
        ) : null}
        {query.refreshError ? <p role="status" className="mt-4 rounded-xl border border-gold/25 bg-gold/[0.07] p-3 text-sm text-gold">Morning Brief refresh failed; showing retained state. {query.refreshError}</p> : null}
        {announcement ? <p role="status" aria-live="polite" className="mt-4 rounded-xl border border-white/10 bg-black/20 p-3 text-sm text-stone-200">{announcement}</p> : null}
      </section>

      <section aria-labelledby="morning-section-0" className="space-y-4">
        <SectionHeading
          section={synthesis.changes_since_meaningful_check}
          index={0}
          countLabel={`${synthesis.briefing.material_change_count} material`}
        />
        <div className="grid gap-4">
          {(materialChanges.length ? materialChanges : synthesis.changes_since_meaningful_check.statements.slice(0, 1)).map((item) => (
            <StatementCard
              key={item.statement_id}
              statement={item}
              onCorrection={applyCorrection}
              onProviderPreview={openProviderPreview}
              history={history[item.statement_id]}
              historyLoading={historyLoading === item.statement_id}
              loadHistory={() => void loadHistory(item.statement_id)}
              undoCorrection={undoCorrection}
              pending={pending}
              compact
            />
          ))}
        </div>
      </section>

      <section aria-labelledby="morning-section-1" className="space-y-4">
        <SectionHeading
          section={synthesis.attention_today}
          index={1}
          countLabel={`${synthesis.urgent_attention_count} supported`}
        />
        {remainingAttention.length ? (
          <div className="grid gap-4">
            {remainingAttention.map((item) => {
              const caution = synthesis.briefing.review_cautions[item.statement_id];
              return (
                <div key={item.statement_id}>
                  <StatementCard
                    statement={item}
                    onCorrection={applyCorrection}
                    onProviderPreview={openProviderPreview}
                    history={history[item.statement_id]}
                    historyLoading={historyLoading === item.statement_id}
                    loadHistory={() => void loadHistory(item.statement_id)}
                    undoCorrection={undoCorrection}
                    pending={pending}
                    forceReview={Boolean(caution)}
                    displaySummary={caution ?? undefined}
                  />
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm leading-6 text-stone-300">
            {primaryStatement
              ? "The leading item above is the only supported attention item in this brief."
              : synthesis.attention_today.statements[0]?.summary}
          </div>
        )}
      </section>

      <section aria-labelledby="morning-section-2" className="space-y-4">
        <SectionHeading
          section={synthesis.handled_paused_waiting}
          index={2}
          countLabel={`${synthesis.handled_paused_waiting.total_count} tracked`}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <ControlCount value={synthesis.briefing.handled_count} label="already handled" />
          <ControlCount value={synthesis.briefing.waiting_count} label="waiting or intentionally paused" />
          <ControlCount value={synthesis.briefing.upcoming_count} label="protected for later" />
        </div>
        {supportHighlights.length ? (
          <div className="grid gap-3 md:grid-cols-3">
            {supportHighlights.map((item) => (
              <StatementCard
                key={item.statement_id}
                statement={item}
                onCorrection={applyCorrection}
                onProviderPreview={openProviderPreview}
                history={history[item.statement_id]}
                historyLoading={historyLoading === item.statement_id}
                loadHistory={() => void loadHistory(item.statement_id)}
                undoCorrection={undoCorrection}
                pending={pending}
                compact
              />
            ))}
          </div>
        ) : null}
        {remainingSupport.length ? (
          <details className="rounded-2xl border border-white/10 bg-white/[0.025]">
            <summary className="flex min-h-12 cursor-pointer items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-stone-300">
              Review {remainingSupport.length} more supporting item{remainingSupport.length === 1 ? "" : "s"}
              <ChevronDown className="h-4 w-4" aria-hidden="true" />
            </summary>
            <div className="grid gap-3 border-t border-white/10 p-3 md:grid-cols-2">
              {remainingSupport.map((item) => (
                <StatementCard
                  key={item.statement_id}
                  statement={item}
                  onCorrection={applyCorrection}
                  onProviderPreview={openProviderPreview}
                  history={history[item.statement_id]}
                  historyLoading={historyLoading === item.statement_id}
                  loadHistory={() => void loadHistory(item.statement_id)}
                  undoCorrection={undoCorrection}
                  pending={pending}
                  compact
                />
              ))}
            </div>
          </details>
        ) : null}
      </section>

      <section aria-labelledby="morning-section-3" className="space-y-4">
        <SectionHeading
          section={synthesis.project_momentum_constraints}
          index={3}
          countLabel={`${synthesis.briefing.project_count} projects`}
        />
        <div className="grid gap-3 md:grid-cols-2">
          {synthesis.project_momentum_constraints.statements.map((item) => (
            <StatementCard
              key={item.statement_id}
              statement={item}
              onCorrection={applyCorrection}
              onProviderPreview={openProviderPreview}
              history={history[item.statement_id]}
              historyLoading={historyLoading === item.statement_id}
              loadHistory={() => void loadHistory(item.statement_id)}
              undoCorrection={undoCorrection}
              pending={pending}
              compact
            />
          ))}
        </div>
      </section>

      <section aria-labelledby="morning-section-4" className="space-y-4">
        <SectionHeading
          section={synthesis.realistic_day_shape}
          index={4}
          countLabel={`${synthesis.briefing.fixed_commitment_count} fixed`}
        />
        <div className="grid gap-3 md:grid-cols-2">
          {synthesis.realistic_day_shape.statements.map((item) => (
            <StatementCard
              key={item.statement_id}
              statement={item}
              onCorrection={applyCorrection}
              onProviderPreview={openProviderPreview}
              history={history[item.statement_id]}
              historyLoading={historyLoading === item.statement_id}
              loadHistory={() => void loadHistory(item.statement_id)}
              undoCorrection={undoCorrection}
              pending={pending}
              compact
            />
          ))}
        </div>
      </section>

      <section aria-label="Morning correction ledger" className="rounded-[1.6rem] border border-white/10 bg-white/[0.025] p-3 sm:p-4">
        <CorrectionHistory
          records={ledger}
          loading={ledgerLoading}
          onLoad={() => void loadLedger()}
          onUndo={undoCorrection}
          pending={pending}
          title="All Morning corrections and undo"
        />
      </section>

      {synthesis.provider_diagnostics.length ? (
        <details className="rounded-[1.6rem] border border-white/10 bg-white/[0.035]">
          <summary id="morning-limitations" className="flex min-h-12 cursor-pointer items-center justify-between gap-3 px-5 py-4 text-sm font-medium text-stone-300">
            Evidence limitations
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
          </summary>
          <ul className="list-disc space-y-2 border-t border-white/10 px-9 py-4 text-sm leading-6 text-stone-400">{synthesis.provider_diagnostics.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 py-4 text-sm text-stone-500">
        <p className="inline-flex items-center gap-2"><Sparkles className="h-4 w-4" aria-hidden="true" /> Grounded in current connected reality.</p>
        <Link href="/today" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/10 px-4 text-stone-200 hover:bg-white/[0.06]">Open Today <ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link>
      </div>

      <ProviderDialog open={dialogOpen} preview={preview} loading={previewLoading} error={previewError} confirming={confirming} close={closeDialog} confirm={confirmProviderChange} />
    </div>
  );
}
