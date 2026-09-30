"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { collegeApiRequest, CollegeRequestError, formatDateTime, type CollegeBriefProjection } from "@/lib/api";
import { readAgentSettings } from "@/lib/settings";
import {
  collegeRecordGroups,
  collegeDeliveryKey,
  readCollegeDelivery,
  writeCollegeDelivery,
  type PendingCollegeCommand,
  collegeClaimDisplay,
  collegeConflictDisplay,
  capturePreferenceCopy,
  invalidateDependentCollegeDetails,
  createCollegeReadGate,
  collectCollegePages,
  knownPrecommitRejection,
  readableCollegeField,
  readableCollegeValue,
  sourceLabel,
  type CollegeAcknowledgment,
  type CollegeConsent,
  type CollegeContext,
  type CollegeRecord,
  type CollegeStatePage,
} from "@/lib/college-review";

import { onRuntimeSessionChange, syntheticRuntime } from "@/lib/runtime-session";

const MAX_RECORDS = 50;
const MAX_PAGES = 4;

function body(value: Record<string, unknown>) {
  return { method: "POST", body: JSON.stringify(value) };
}

function identity() {
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID() };
}

const transientView = new Map<string, { announcement: string; selectedBinding: string }>();

onRuntimeSessionChange(() => transientView.clear());

function outboxScope() {
  const settings = readAgentSettings();
  return `${settings.collegeUrl}\u0000${settings.apiKey}`;
}

function commandSettled(result: unknown): boolean {
  if (!result || typeof result !== "object") return false;
  const value = result as { outcome?: string; state?: string; receipt_state?: string };
  return ["applied", "saved_for_review", "rejected", "needs_review"].includes(
    value.outcome || value.receipt_state || value.state || "",
  );
}

function requestWindow() {
  const start = new Date();
  const end = new Date(start.getTime() + 48 * 60 * 60 * 1000);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  return `scope=cross_course&horizon_start=${encodeURIComponent(start.toISOString())}&horizon_end=${encodeURIComponent(end.toISOString())}&timezone=${encodeURIComponent(timezone)}&limit=${MAX_RECORDS}`;
}

async function loadRecordedState(): Promise<CollegeStatePage> {
  return collectCollegePages(requestWindow(), (path) => collegeApiRequest<CollegeStatePage>(path), MAX_PAGES);
}

function receiptCopy(ack: CollegeAcknowledgment): string {
  if (ack.outcome === "applied") return "Saved to shared College state. No outside account was changed.";
  if (ack.outcome === "saved_for_review") return ack.review?.prompt
    ? `Saved for review. No uncertain detail was confirmed. ${ack.review.prompt}`
    : "Saved for review. No uncertain detail was confirmed.";
  if (ack.outcome === "pending") return "Received. Check the result before sending this report again.";
  if (ack.outcome === "uncertain") return "The result is uncertain. Check the saved request before retrying.";
  return "The report was not recorded.";
}

export function CollegeReview({ brief, briefStale = false, showContext = true, onPendingChange, onChange }: { brief: CollegeBriefProjection; briefStale?: boolean; showContext?: boolean; onPendingChange?: (pending: boolean) => void; onChange?: () => Promise<void> }) {
  const [consent, setConsent] = useState<CollegeConsent | null>(null);
  const [context, setContext] = useState<CollegeContext | null>(null);
  const [bindings, setBindings] = useState<Array<{ binding_id: string; label: string }>>([]);
  const [selectedBinding, setSelectedBinding] = useState(() => transientView.get(outboxScope())?.selectedBinding || "");
  const [state, setState] = useState<CollegeStatePage | null>(null);
  const [message, setMessage] = useState("");
  const [announcement, setAnnouncement] = useState(() => transientView.get(outboxScope())?.announcement || "");
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [actionBusy, setBusy] = useState(false);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const busy = actionBusy || !recoveryReady;
  const deliveryKey = useRef<string | null>(null);
  const [pendingCommand, setPendingCommand] = useState<PendingCollegeCommand | null>(null);
  useEffect(() => { onPendingChange?.(Boolean(pendingCommand)); }, [pendingCommand, onPendingChange]);
  const [retryAvailable, setRetryAvailable] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{ kind: "claim" | "context"; id: string } | null>(null);
  const factsDisclosure = useRef<HTMLDetailsElement | null>(null);
  const confirmButton = useRef<HTMLButtonElement | null>(null);
  const readGate = useRef(createCollegeReadGate());

  useEffect(() => {
    let active = true;
    const settings = readAgentSettings();
    void collegeDeliveryKey(settings.collegeUrl, settings.apiKey).then((key) => {
      if (syntheticRuntime) {
        for (const retained of Object.keys(sessionStorage)) {
          if (retained.startsWith("pcos.college.delivery.") && retained !== key) sessionStorage.removeItem(retained);
        }
      }
      const pending = readCollegeDelivery(sessionStorage, key);
      if (!active) return;
      deliveryKey.current = key;
      setPendingCommand(pending);
      setRecoveryReady(true);
    }).catch(() => {
      if (active) setError("Pending-request recovery is unavailable. Changes are blocked to prevent duplicate delivery. Restore this tab's storage access and reload.");
    });
    return () => { active = false; };
  }, []);

  function savePending(command: PendingCollegeCommand | null) {
    if (!deliveryKey.current) throw new Error("Wait for pending-request recovery before making a change.");
    setPendingCommand(writeCollegeDelivery(sessionStorage, deliveryKey.current, command));
  }

  useEffect(() => {
    if (!pendingCommand?.expiresAt || pendingCommand.retryExpired) return;
    const timer = window.setTimeout(() => {
      try {
        const pending = readCollegeDelivery(sessionStorage, deliveryKey.current!);
        setPendingCommand(pending);
        setRetryAvailable(false);
      } catch {
        setRecoveryReady(false);
        setError("Pending-request recovery is unavailable. Reload after restoring this tab's storage access.");
      }
    }, Math.max(0, pendingCommand.expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [pendingCommand]);

  const load = useCallback(async () => {
    const generation = readGate.current.begin();
    const results = await Promise.allSettled([
      collegeApiRequest<CollegeConsent>("/college/surface/consent"),
      collegeApiRequest<CollegeContext>("/college/surface/context?limit=12"),
      loadRecordedState(),
      collegeApiRequest<{ bindings: Array<{ binding_id: string; label: string }> }>("/college/surface/bindings"),
    ]);
    if (!readGate.current.isCurrent(generation)) return;
    if (results[0].status === "fulfilled") setConsent(results[0].value);
    if (results[1].status === "fulfilled") setContext(results[1].value);
    if (results[2].status === "fulfilled") setState(results[2].value);
    if (results[3].status === "fulfilled") setBindings(results[3].value.bindings);
    const failures = results.filter((item) => item.status === "rejected");
    setRefreshError(failures.length ? "Some College details could not refresh. Previously loaded details remain visible; check the connection and scope." : "");
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (confirmTarget) confirmButton.current?.focus(); }, [confirmTarget]);
  useEffect(() => {
    transientView.set(outboxScope(), { announcement, selectedBinding });
    if (transientView.size > 8) transientView.delete(transientView.keys().next().value || "");
  }, [announcement, selectedBinding]);

  const groups = useMemo(() => collegeRecordGroups(state?.records ?? []), [state]);
  const subjects = useMemo(() => new Map(groups.identities.map((item) => [item.canonical_id, String(item.attributes.name || item.attributes.title || item.attributes.label || "College item")])), [groups.identities]);

  function announce(value: string) {
    transientView.set(outboxScope(), { announcement: value, selectedBinding });
    setAnnouncement(value);
  }

  function invalidateAfterMutation(includeFacts: boolean) {
    readGate.current.invalidate();
    if (includeFacts) {
      setState((current) => invalidateDependentCollegeDetails(current));
      setContext((current) => current && { ...current, items: [] });
    } else {
      setConsent(null);
    }
  }

  async function runAction(action: () => Promise<void>, refreshParent = false) {
    setBusy(true);
    setError("");
    try {
      await action();
      if (refreshParent && onChange) await onChange();
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "College review could not complete.");
    } finally {
      setBusy(false);
    }
  }

  async function sendCommand<T>(path: string, payload: Record<string, unknown>, label: string): Promise<T> {
    if (!recoveryReady || pendingCommand) throw new Error("Check the earlier College request before making another change.");
    if (!readAgentSettings().apiKey) throw new Error("Add your API key in Settings before recording a College change.");
    const pending = { path, payload, label };
    savePending(pending);
    setRetryAvailable(false);
    let result: T;
    try {
      result = await collegeApiRequest<T>(path, body(payload));
    } catch (cause) {
      if (cause instanceof CollegeRequestError && knownPrecommitRejection(cause.status)) {
        savePending(null);
      }
      throw cause;
    }
    if (commandSettled(result)) {
      savePending(null);
    }
    return result;
  }

  function toggleConsent() {
    if (pendingCommand) return;
    void runAction(async () => {
      const operation = consent?.active ? "revoke" : "grant";
      await sendCommand("/college/surface/consent", {
        operation, ...identity(), ...(operation === "revoke" ? { expected_revision: consent?.revision } : {}),
      }, "capture consent");
      invalidateAfterMutation(false);
      announce(operation === "grant" ? "College update capture is on. Only clear operational updates are recorded; you can review or revoke this choice here." : "Automatic College update capture is off. Prior saved information remains available for review.");
    }, true);
  }

  function capture() {
    if (pendingCommand) return;
    const report = message.trim();
    if (!report) return;
    const request = identity();
    void runAction(async () => {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const acknowledgment = await sendCommand<CollegeAcknowledgment>("/college/update", {
        operation: "capture", ...request, message: report, source_surface: "app",
        conversation_id: "pcos-app-college-capture", asserted_at: new Date().toISOString(), timezone,
        ...(selectedBinding ? { binding_id: selectedBinding, explicitly_selected_binding: true } : {}),
      }, "College report");
      announce(receiptCopy(acknowledgment));
      if (acknowledgment.outcome === "applied" || acknowledgment.outcome === "saved_for_review") {
        invalidateAfterMutation(true);
        setMessage("");
      }
    }, true);
  }

  function checkStatus() {
    if (!pendingCommand) return;
    void runAction(async () => {
      const result = await collegeApiRequest<{ status: string; source: string; outcome_hint?: string; receipt: { state: string } | null }>(`/college/surface/update-status?command_id=${encodeURIComponent(String(pendingCommand.payload.command_id))}`);
      if (result.status === "found") {
        const recorded = result.receipt?.state;
        announce(result.outcome_hint === "saved_for_review"
          ? "This report was saved for review; no uncertain detail became a confirmed College fact."
          : recorded === "applied" ? "This change was saved. No outside account was changed."
          : `Saved request is ${readableCollegeField(recorded || "pending")}.`);
        if (["applied", "needs_review", "rejected"].includes(recorded || "")) {
          savePending(null);
          if (pendingCommand.label === "College report" && recorded !== "rejected") setMessage("");
          if (recorded !== "rejected") {
            invalidateAfterMutation(pendingCommand.label !== "capture consent");
            if (onChange) await onChange();
          }
        } else if (recorded === "retryable_failure") {
          setRetryAvailable(!pendingCommand.retryExpired);
          announce("The saved attempt failed before completion. You may retry the exact same request.");
        }
      } else {
        announce("No saved result is available yet. Keep this report until its outcome is clear.");
        setRetryAvailable(!pendingCommand.retryExpired);
      }
    });
  }

  function retryExact() {
    if (!pendingCommand || !retryAvailable || pendingCommand.retryExpired) return;
    void runAction(async () => {
      const sameRequest = readCollegeDelivery(sessionStorage, deliveryKey.current!);
      if (!sameRequest || sameRequest.retryExpired) {
        setPendingCommand(sameRequest);
        setRetryAvailable(false);
        return;
      }
      let result: { outcome?: string; state?: string; receipt_state?: string };
      try {
        result = await collegeApiRequest(sameRequest.path, body(sameRequest.payload));
      } catch (cause) {
        if (cause instanceof CollegeRequestError && knownPrecommitRejection(cause.status)) {
          savePending(null);
          setRetryAvailable(false);
        }
        throw cause;
      }
      if (commandSettled(result)) {
        savePending(null);
        setRetryAvailable(false);
        const disposition = result.outcome || result.receipt_state || result.state;
        if (disposition !== "rejected") invalidateAfterMutation(sameRequest.label !== "capture consent");
        announce(disposition === "rejected" ? "The original request was rejected without a change." : disposition === "saved_for_review" || disposition === "needs_review" ? "The original report is saved for review." : "The original request was saved. No outside account was changed.");
        if (sameRequest.label === "College report" && disposition !== "rejected") setMessage("");
      } else {
        setRetryAvailable(false);
        announce("The original request is still pending. Check its saved result before trying again.");
      }
    }, true);
  }

  function contextAction(item: CollegeContext["items"][number], operation: "correct" | "remove_raw" | "forget") {
    if (pendingCommand) return;
    const replacement = editValue.trim();
    if (operation === "correct" && !replacement) return;
    if (operation === "forget" && (confirmTarget?.kind !== "context" || confirmTarget.id !== item.item_id)) {
      setConfirmTarget({ kind: "context", id: item.item_id });
      return;
    }
    setConfirmTarget(null);
    void runAction(async () => {
      await sendCommand("/college/surface/context", {
        operation, ...identity(), item_id: item.item_id, expected_revision: item.revision,
        ...(operation === "correct" ? { summary: replacement } : {}),
      }, "saved context change");
      invalidateAfterMutation(true);
      setEditId(null);
      setEditValue("");
      announce(operation === "forget" ? "That saved context was forgotten. Dependent PCOS material was retracted." : operation === "remove_raw" ? "Raw source removed. Reviewed derived context may remain; source text can no longer be inspected." : "Correction saved for review. Related interpretations may need review.");
    }, true);
  }

  function claimAction(item: Extract<CollegeRecord, { record_type: "claim" }>, operation: "correct_claim" | "undo_update" | "forget_claim") {
    if (pendingCommand) return;
    if (operation === "forget_claim" && (confirmTarget?.kind !== "claim" || confirmTarget.id !== item.claim_id)) {
      setConfirmTarget({ kind: "claim", id: item.claim_id });
      return;
    }
    setConfirmTarget(null);
    const value = editValue.trim();
    if (operation === "correct_claim" && !value) return;
    void runAction(async () => {
      const ack = await sendCommand<CollegeAcknowledgment>("/college/update", {
        operation, ...identity(), claim_id: item.claim_id, expected_revision: item.revision,
        ...(operation === "correct_claim" ? { value } : {}),
      }, "claim change");
      // A failed follow-up read must not revive an old value after mutation.
      invalidateAfterMutation(true);
      announce(receiptCopy(ack));
      setEditId(null);
      setEditValue("");
    }, true);
  }

  const coverage = groups.coverage;
  const blinn = state?.coverage_expectations.find((item) => item.provider.toLowerCase() === "blinn");
  const sourceIdentities = [
    { name: "Texas A&M mail", aliases: ["tamu", "tamu_gmail", "texas_a&m"] },
    { name: "Personal Gmail", aliases: ["personal_gmail", "gmail_personal", "personal"] },
  ];

  return (
    <section aria-labelledby="college-review-heading" className="college-secondary min-w-0 space-y-4 rounded-[1.7rem] border border-white/10 bg-white/[0.035] p-4 sm:p-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.2em] text-moss">College</p>
        <h2 tabIndex={-1} id="college-review-heading" className="mt-2 text-xl font-semibold text-pearl">{pendingCommand ? "Let’s check whether your update saved" : groups.conflicts.length ? "Some saved details disagree" : "Keep your College details up to date"}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-300">{pendingCommand ? "Check the original result before sending another update. Keep this tab open until delivery is resolved." : groups.conflicts.length ? "Review the conflicting details before relying on them. PCOS has not chosen a side." : "Review saved school details or share a supported class update."}</p>
        {pendingCommand ? <div className="mt-3 rounded-xl border border-gold/25 bg-gold/[0.05] p-3 text-sm">
          <button type="button" disabled={busy} onClick={checkStatus} className="min-h-11 rounded-xl bg-moss px-4 font-semibold text-ink disabled:opacity-50">Check saved result</button>
          {retryAvailable ? <button type="button" disabled={busy} onClick={retryExact} className="ml-2 min-h-11 rounded-xl border border-white/15 px-3 text-stone-200 disabled:opacity-50">Retry same request</button> : null}
          {pendingCommand.retryExpired ? <p className="mt-2 text-gold">The local retry copy has expired. You can still check the original result. Do not send this update again as a new report.</p> : null}
          <details className="mt-2 text-stone-400"><summary className="min-h-11 cursor-pointer py-2">How recovery works</summary><p>This tab retains the original request through reloads. Its local text is cleared when resolved or after seven days. Closing the tab or clearing browser data can remove recovery information.</p><p className="mt-2">Pending change: {pendingCommand.label}</p></details>
        </div> : groups.conflicts.length ? <button type="button" onClick={() => { if (factsDisclosure.current) { factsDisclosure.current.open = true; factsDisclosure.current.scrollIntoView({ block: "start" }); } }} className="mt-3 min-h-11 rounded-xl bg-moss px-4 text-sm font-semibold text-ink">Review conflicting details</button> : null}
      </div>

      {announcement ? <p role="status" aria-live="polite" className="rounded-xl border border-moss/25 bg-moss/[0.07] p-3 text-sm text-stone-200">{announcement}</p> : null}
      {error ? <p role="alert" className="rounded-xl border border-coral/30 bg-coral/[0.07] p-3 text-sm text-coral">{error}{pendingCommand ? " Check the saved result before sending again." : ""}</p> : null}
      {refreshError ? <p role="status" className="rounded-xl border border-gold/25 bg-gold/[0.06] p-3 text-sm text-gold">{refreshError}</p> : null}

      <details className="college-capture rounded-2xl border border-white/10 bg-black/15 p-4"><summary className="min-h-11 cursor-pointer py-2 font-medium">Share a class update</summary>
        <p className="mb-3 text-sm leading-6 text-stone-400">Supports the reviewed Calc topic/check/warning, ENGR Topic 4 individual/team, and derivatives/definition-problems reports. Other wording is saved for review, not interpreted as a confirmed fact.</p>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>

            <p className="mt-1 text-sm text-stone-400">{consent?.active ? "Saving is on for supported class updates. Other wording stays for review." : capturePreferenceCopy(consent)}</p>
            <details className="mt-2 text-xs leading-5 text-stone-400"><summary className="min-h-11 cursor-pointer py-2">Capture settings and privacy</summary><p>Opt in to save clear class updates. This does not permit changes to email, tasks, or Calendar. Sensitive narrative is not automatically retained.</p>{consent?.active ? <p className="mt-2">On since {consent.granted_at ? formatDateTime(consent.granted_at) : "your last choice"}.</p> : null}
              <button type="button" disabled={busy || Boolean(pendingCommand) || !consent} onClick={toggleConsent} className="min-h-11 rounded-xl border border-white/15 px-4 text-sm font-medium text-pearl hover:bg-white/10 disabled:opacity-50">{consent === null ? "Check capture preference" : consent.active ? "Turn capture off" : "Opt in"}</button>
              <p className="mt-2">Unresolved requests stay in this tab through reloads, for up to seven days. Resolve delivery before closing this tab or clearing browser data.</p>
            </details>
          </div>

        </div>
        {consent?.active ? (
          <form className="mt-3" onSubmit={(event) => { event.preventDefault(); capture(); }}>
            {bindings.length ? <label className="mb-3 block text-sm text-stone-200">Course for this update
              <select value={selectedBinding} onChange={(event) => setSelectedBinding(event.target.value)} className="mt-2 min-h-11 w-full rounded-xl border border-white/15 bg-black/60 px-3 text-pearl">
                <option value="">Choose a course (optional)</option>
                {bindings.map((item) => <option key={item.binding_id} value={item.binding_id}>{item.label}</option>)}
              </select>
            </label> : <p className="mb-3 text-sm text-gold">No reviewed course is available to select. You can still save the report for course review.</p>}

            <label htmlFor="college-capture" className="block text-sm font-medium text-stone-200">What changed at school?</label>
            <textarea id="college-capture" rows={3} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="We covered derivatives today, and I still need help with definition problems…" className="mt-2 w-full resize-y rounded-xl border border-white/15 bg-black/25 p-3 text-base text-pearl placeholder:text-stone-500" />
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="submit" disabled={busy || !message.trim() || Boolean(pendingCommand)} className="min-h-11 rounded-xl bg-moss px-4 text-sm font-semibold text-ink disabled:opacity-50">Save update</button>
            </div>
          </form>
        ) : null}
      </details>


      {briefStale ? <p role="status" className="rounded-xl border border-gold/25 bg-gold/[0.06] p-3 text-sm text-gold">The brief needs a successful refresh after a College change. Its previous judgment is hidden.</p> : showContext ? <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-black/15 p-4">
          <h3 className="font-medium text-pearl">Upcoming context</h3>
          {brief.session_changes.length ? <ul className="mt-2 space-y-2 text-sm leading-6 text-stone-300">{brief.session_changes.slice(0, 3).map((item) => <li key={`${item.subject_id}:${item.source_order}`}>{item.summary}</li>)}</ul> : <p className="mt-2 text-sm text-stone-400">No class changes are recorded in this brief.</p>}
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/15 p-4">
          <h3 className="font-medium text-pearl">What can wait</h3>
          {brief.safe_to_wait.length ? <ul className="mt-2 space-y-2 text-sm leading-6 text-stone-300">{brief.safe_to_wait.slice(0, 3).map((item) => <li key={`${item.subject_id}:${item.source_order}`}>{item.summary}</li>)}</ul> : <p className="mt-2 text-sm text-stone-400">Nothing is confirmed safe to put off.</p>}
        </div>
      </div> : null}

      <details ref={factsDisclosure} className="scroll-mt-28 rounded-2xl border border-white/10 bg-black/15">
        <summary className="min-h-12 cursor-pointer px-4 py-3 font-medium text-stone-200">Review saved facts and questions</summary>
        <div className="space-y-4 border-t border-white/10 p-4">
          {groups.conflicts.length ? <div className="space-y-2 rounded-xl border border-gold/25 bg-gold/[0.05] p-3 text-sm"><p className="font-medium text-gold">{groups.conflicts.length} recorded conflict{groups.conflicts.length === 1 ? " needs" : "s need"} review. PCOS has not chosen a side.</p><ul className="space-y-2">{groups.conflicts.slice(0, 8).map((item) => <li key={item.record_id} className="text-stone-300"><span className="font-medium text-pearl">{subjects.get(item.subject_id) || "College item"} · {collegeConflictDisplay(item.field, item.reason).field}:</span> Saved details disagree.<details className="mt-1"><summary className="min-h-11 cursor-pointer py-2 text-xs">Why this needs review</summary><p className="text-xs">{collegeConflictDisplay(item.field, item.reason).reason}</p></details></li>)}</ul>{groups.conflicts.length > 8 ? <p className="text-xs text-stone-400">More conflicts are in the bounded recorded view.</p> : null}</div> : null}
          {groups.claims.length ? <ul className="space-y-3">{groups.claims.slice(0, 12).map((item) => (
            <li key={item.claim_id} className="rounded-xl border border-white/10 p-3 text-sm">
              <p className="font-medium text-pearl">{subjects.get(item.subject_id) || "College item"} · {collegeClaimDisplay(item.field, item.value).title}</p>
              <p className="mt-1 break-words text-stone-300">{item.field === "learning_need" && item.value && typeof item.value === "object" ? typeof (item.value as Record<string, unknown>).statement === "string" ? `Reported learning need: ${String((item.value as Record<string, unknown>).statement)}` : "A learning need is recorded. Review the saved details below." : collegeClaimDisplay(item.field, item.value).detail}</p>
              {collegeClaimDisplay(item.field, item.value).qualification ? <p className="mt-1 text-xs text-gold">{collegeClaimDisplay(item.field, item.value).qualification}</p> : null}

              <details className="mt-2 rounded-lg border border-white/10 bg-white/[0.025]">
                <summary className="min-h-11 cursor-pointer px-3 py-2 text-xs text-stone-300">Why this is recorded</summary>
                <div className="space-y-2 border-t border-white/10 p-3 text-xs leading-5 text-stone-400">
                  <p className="mt-2 text-xs text-stone-400">{sourceLabel(item.source_class)} · {readableCollegeField(item.claim_status)} · {readableCollegeField(item.certainty)} · Recorded {formatDateTime(item.recorded_at)}</p>
                  <p>{sourceLabel(item.source_class)} · {readableCollegeField(item.certainty)}. This is evidence of the attributed report, not proof of a provider submission, grade, or official deadline.</p>
                  {item.value && typeof item.value === "object" ? <p className="break-words">Saved details: {readableCollegeValue(item.value)}</p> : null}
                  <p>{item.evidence_refs.length ? `${item.evidence_refs.length} retained evidence reference${item.evidence_refs.length === 1 ? "" : "s"}.` : "No detailed evidence reference is exposed."}</p>
                  {item.evidence_refs.length ? <details><summary className="min-h-11 cursor-pointer py-2">Technical references</summary><ul className="space-y-1 break-all">{item.evidence_refs.slice(0, 4).map((reference) => <li key={reference}>{reference}</li>)}</ul></details> : null}
                </div>
              </details>
              <div className="mt-3 flex flex-wrap gap-2">
                {item.field !== "deadline" && typeof item.value === "string" ? <button type="button" disabled={busy || Boolean(pendingCommand)} onClick={() => { setEditId(item.claim_id); setEditValue(item.value as string); }} className="min-h-11 rounded-lg border border-white/15 px-3 text-stone-200">Correct</button> : null}
                <button type="button" disabled={busy || Boolean(pendingCommand)} onClick={() => claimAction(item, "undo_update")} className="min-h-11 rounded-lg border border-white/15 px-3 text-stone-200">Undo PCOS update</button>
                <button type="button" disabled={busy || Boolean(pendingCommand)} onClick={() => claimAction(item, "forget_claim")} className="min-h-11 rounded-lg border border-coral/30 px-3 text-coral">Forget</button>
              </div>
              {confirmTarget?.kind === "claim" && confirmTarget.id === item.claim_id ? <div className="mt-3 rounded-lg border border-coral/30 p-3 text-sm text-stone-200"><p>Forget this claim and unsupported dependent PCOS material?</p><div className="mt-2 flex gap-2"><button ref={confirmButton} type="button" disabled={busy} onClick={() => claimAction(item, "forget_claim")} className="min-h-11 rounded-lg bg-coral px-3 text-ink">Yes, forget</button><button type="button" onClick={() => setConfirmTarget(null)} className="min-h-11 rounded-lg border border-white/15 px-3">Cancel</button></div></div> : null}
              {typeof item.value === "object" || item.field === "deadline" ? <p className="mt-2 text-xs text-stone-400">To correct this detail, describe the change in a class update.</p> : null}
              {editId === item.claim_id ? <div className="mt-3 flex flex-wrap gap-2"><label className="flex-1"><span className="sr-only">Correct recorded value</span><input value={editValue} onChange={(event) => setEditValue(event.target.value)} className="min-h-11 w-full rounded-lg border border-white/15 bg-black/25 px-3 text-pearl" /></label><button type="button" disabled={busy || !editValue.trim()} onClick={() => claimAction(item, "correct_claim")} className="min-h-11 rounded-lg bg-moss px-3 text-ink">Save correction</button></div> : null}
            </li>
          ))}</ul> : <p className="text-sm text-stone-400">No claim details are available in this bounded view.</p>}
          {state?.status !== "ready" ? <p className="text-sm text-gold">Recorded College details are {readableCollegeField(state?.status || "unavailable")} in this scope. No empty or complete state is implied.</p> : null}

          {state?.pagination.next_cursor ? <p className="text-xs text-stone-400">More recorded details exist. This view shows at most {MAX_RECORDS * MAX_PAGES} items from one unchanged snapshot.</p> : null}
        </div>
      </details>

      <details className="rounded-2xl border border-white/10 bg-black/15">
        <summary className="min-h-12 cursor-pointer px-4 py-3 font-medium text-stone-200">Review saved context and removal</summary>
        <div className="space-y-3 border-t border-white/10 p-4">
          {context?.items.length ? context.items.map((item) => <article key={item.item_id} className="rounded-xl border border-white/10 p-3 text-sm">
            <p className="break-words text-stone-200">{item.summary}</p>
            <p className="mt-1 text-xs text-stone-400">{readableCollegeField(item.status)} · {formatDateTime(item.asserted_at)} · Raw source {item.raw_source_available ? "available during its correction window" : "unavailable"}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" disabled={busy || Boolean(pendingCommand)} onClick={() => { setEditId(item.item_id); setEditValue(item.summary); }} className="min-h-11 rounded-lg border border-white/15 px-3 text-stone-200">Correct</button>
              {item.raw_source_available ? <button type="button" disabled={busy || Boolean(pendingCommand)} onClick={() => contextAction(item, "remove_raw")} className="min-h-11 rounded-lg border border-white/15 px-3 text-stone-200">Remove raw source only</button> : null}
              <button type="button" disabled={busy || Boolean(pendingCommand)} onClick={() => contextAction(item, "forget")} className="min-h-11 rounded-lg border border-coral/30 px-3 text-coral">Forget context</button>
            </div>
            {confirmTarget?.kind === "context" && confirmTarget.id === item.item_id ? <div className="mt-3 rounded-lg border border-coral/30 p-3 text-sm text-stone-200"><p>Forget this context and unsupported dependent PCOS material?</p><div className="mt-2 flex gap-2"><button ref={confirmButton} type="button" disabled={busy} onClick={() => contextAction(item, "forget")} className="min-h-11 rounded-lg bg-coral px-3 text-ink">Yes, forget</button><button type="button" onClick={() => setConfirmTarget(null)} className="min-h-11 rounded-lg border border-white/15 px-3">Cancel</button></div></div> : null}
            {editId === item.item_id ? <div className="mt-3 flex gap-2"><label className="flex-1"><span className="sr-only">Correct saved context</span><input value={editValue} onChange={(event) => setEditValue(event.target.value)} className="min-h-11 w-full rounded-lg border border-white/15 bg-black/25 px-3 text-pearl" /></label><button type="button" disabled={busy || !editValue.trim()} onClick={() => contextAction(item, "correct")} className="min-h-11 rounded-lg bg-moss px-3 text-ink">Save</button></div> : null}
          </article>) : <p className="text-sm text-stone-400">No reviewable saved context is available in this scope.</p>}
          <p className="text-xs leading-5 text-stone-400">Removing raw source text can leave a reviewed derived fact in PCOS. Forgetting retracts the selected fact and unsupported dependent PCOS material. Neither action deletes copies held by an outside conversation host or provider.</p>
        </div>
      </details>

      <details className="rounded-2xl border border-white/10 bg-black/15">
        <summary className="min-h-12 cursor-pointer px-4 py-3 font-medium text-stone-200">Sources, coverage, and action safeguards</summary>
        <div className="space-y-3 border-t border-white/10 p-4 text-sm leading-6 text-stone-300">
          <button type="button" disabled={busy} onClick={() => void load()} className="min-h-11 rounded-xl border border-white/15 px-4 text-sm disabled:opacity-50">Refresh College details</button>
          {sourceIdentities.map((source) => {
            const matches = coverage.filter((item) => source.aliases.includes(item.provider.toLowerCase()));
            return <p key={source.name}><span className="font-medium text-pearl">{source.name}</span>: {matches.length ? "See recorded coverage below." : "No College coverage assessment is available in this bounded view."}</p>;
          })}
          {coverage.slice(0, 8).map((item) => <p key={item.record_id}><span className="font-medium text-pearl">{item.provider}</span>{item.account_id ? ` · ${item.account_id}` : ""}: {readableCollegeField(item.availability)}, {readableCollegeField(item.completeness)} within its recorded bounds, {readableCollegeField(item.freshness)}. {item.assessed_at ? `Recorded ${formatDateTime(item.assessed_at)}.` : "No source check time is recorded."}</p>)}
          <p className="rounded-xl border border-gold/20 bg-gold/[0.05] p-3">Blinn mail is pending administrator approval. Its mailbox has not been checked here; no empty, healthy, or complete state is implied.{!blinn ? " A current College coverage read is unavailable." : ""}</p>
          <p>TAMU, Personal Gmail, and Blinn are separate sources. Source health and completeness are recorded independently; an unavailable source limits conclusions only where it matters to this brief.</p>
          <p>Message-specific unread, important, action-required, uncertain, proposed, confirmed, handled, and informational states are unavailable in this College view because the current authorized read does not expose a bounded message feed. Open the existing email review for its separately scoped messages.</p>
          <p>Any task or Calendar change still requires the existing exact preview and explicit confirmation. Capturing a College update does not approve an outside action.</p>
          <div className="flex flex-wrap gap-x-5 gap-y-1">
            <a href="/email" className="inline-flex min-h-11 items-center text-moss underline underline-offset-4">Open separately scoped email review</a>
            <a href="/chat" className="inline-flex min-h-11 items-center text-moss underline underline-offset-4">Open protected action review in Chat</a>
          </div>
          <p>These existing surfaces do not supply a College message feed or a proposed College action list.</p>
        </div>
      </details>
    </section>
  );
}
