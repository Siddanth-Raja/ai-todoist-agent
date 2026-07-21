"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  CircleDashed,
  LockKeyhole,
  MailCheck,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Tag,
} from "lucide-react";
import { apiRequest } from "@/lib/api";
import {
  GMAIL_MODIFY_SCOPE,
  MAX_LABEL_CANARY_MESSAGES,
  canConfirmProposal,
  gateHeadline,
  type EmailOrganizationProposal,
  type GmailMutationGateStatus,
} from "@/lib/email-organization";

type PendingEmailAction = {
  pending_action: EmailOrganizationProposal;
};

type EmailExecutionOutcome = {
  action: { lifecycle: string };
  undo_action: EmailOrganizationProposal | null;
  actions_taken: Array<Record<string, unknown>>;
  errors: string[];
};

const stages = [
  {
    title: "Explicit OAuth approval",
    detail: "Not granted. Personal Email remains read-only and Calendar authorization is untouched.",
    icon: LockKeyhole,
  },
  {
    title: "Hand-reviewed label canary",
    detail: `Apply one exact existing user label to no more than ${MAX_LABEL_CANARY_MESSAGES} selected messages.`,
    icon: Tag,
  },
  {
    title: "Verify exact undo",
    detail: "A separate approval removes that same label from the same manifest and verifies the restored state.",
    icon: RotateCcw,
  },
  {
    title: "Unlock later operations",
    detail: "Archive, read-state changes, and larger batches stay locked until the canary and its undo both pass.",
    icon: MailCheck,
  },
];

const reviewDateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatReviewDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Date unavailable" : reviewDateFormatter.format(parsed);
}

export default function EmailPage() {
  const [gate, setGate] = useState<GmailMutationGateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [proposal, setProposal] = useState<EmailOrganizationProposal | null>(null);
  const [selectedTokens, setSelectedTokens] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [lastOutcome, setLastOutcome] = useState<EmailExecutionOutcome | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [gateValue, pendingValue] = await Promise.all([
        apiRequest<GmailMutationGateStatus>("/email/organization/gate"),
        apiRequest<PendingEmailAction | null>(
          "/pending-actions/current?session_id=email-organization",
        ),
      ]);
      setGate(gateValue);
      const pending = pendingValue?.pending_action ?? null;
      setProposal(pending);
      setSelectedTokens(
        pending?.details.targets.map((target) => target.message_token) ?? [],
      );
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to read the local Gmail approval gate.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const state = gate?.state ?? "manual_oauth_required";
  const selectionChanged = Boolean(
    proposal && selectedTokens.length !== proposal.details.targets.length,
  );

  async function adjustProposal() {
    if (!proposal || selectedTokens.length === 0 || !selectionChanged) return;
    setSaving(true);
    setError(null);
    try {
      await apiRequest(`/email/organization/actions/${proposal.action_id}/adjust`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: proposal.version,
          fingerprint: proposal.fingerprint,
          selected_message_tokens: selectedTokens,
        }),
      });
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to adjust the proposal.");
    } finally {
      setSaving(false);
    }
  }

  async function rejectProposal() {
    if (!proposal) return;
    setSaving(true);
    setError(null);
    try {
      await apiRequest("/confirm-cancel", {
        method: "POST",
        body: JSON.stringify({
          session_id: "email-organization",
          action_id: proposal.action_id,
          expected_version: proposal.version,
          fingerprint: proposal.fingerprint,
        }),
      });
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to reject the proposal.");
    } finally {
      setSaving(false);
    }
  }

  async function confirmProposal() {
    if (!proposal || !gate || !canConfirmProposal(proposal, gate)) return;
    setSaving(true);
    setError(null);
    try {
      const outcome = await apiRequest<EmailExecutionOutcome>(`/email/organization/actions/${proposal.action_id}/confirm`, {
        method: "POST",
        body: JSON.stringify({
          session_id: "email-organization",
          action_id: proposal.action_id,
          expected_version: proposal.version,
          fingerprint: proposal.fingerprint,
        }),
      });
      setLastOutcome(outcome);
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to confirm the proposal.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 pb-12">
      <section className="glass-panel overflow-hidden rounded-[2rem] p-5 md:p-7">
        <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.22em] text-moss">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              Personal Email organization
            </div>
            <h3 className="mt-3 text-3xl font-semibold tracking-tight text-pearl">
              Approval boundary is locked
            </h3>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-300">
              SID-230 inventory evidence can support exact proposals, but no mailbox change is available
              until you explicitly approve a separate Personal Gmail reauthorization.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.06] px-4 text-sm text-stone-200 transition hover:bg-white/[0.1] disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Refresh local gate
          </button>
        </div>

        <div className="mt-6 rounded-2xl border border-gold/30 bg-gold/[0.08] p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-gold" aria-hidden="true" />
            <div>
              <p className="font-medium text-gold">{gateHeadline(state)}</p>
              <p className="mt-1 text-sm leading-6 text-stone-300">
                Required later scope: <code className="rounded bg-black/25 px-1.5 py-1 text-xs">{GMAIL_MODIFY_SCOPE}</code>.
                It is displayed for informed approval only; this screen cannot request it or start OAuth.
              </p>
            </div>
          </div>
        </div>

        {error ? (
          <p className="mt-4 rounded-xl border border-coral/30 bg-coral/10 px-4 py-3 text-sm text-coral">
            {error}
          </p>
        ) : null}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        {stages.map((stage, index) => {
          const Icon = stage.icon;
          const complete =
            (index === 0 && Boolean(gate?.oauth_authorized)) ||
            (index === 1 && Boolean(gate?.label_canary_applied)) ||
            (index === 2 && Boolean(gate?.label_canary_undo_verified));
          const active =
            (index === 0 && state === "manual_oauth_required") ||
            (index === 1 && state === "label_canary_required") ||
            (index === 2 && state === "label_canary_undo_required") ||
            (index === 3 && state === "canary_verified");
          return (
            <article
              key={stage.title}
              className={`rounded-[1.6rem] border p-5 ${
                active ? "border-iris/35 bg-iris/[0.08]" : "border-white/10 bg-white/[0.045]"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[0.07]">
                  {complete ? (
                    <CheckCircle2 className="h-5 w-5 text-moss" aria-hidden="true" />
                  ) : active ? (
                    <Icon className="h-5 w-5 text-iris" aria-hidden="true" />
                  ) : (
                    <CircleDashed className="h-5 w-5 text-stone-500" aria-hidden="true" />
                  )}
                </span>
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Stage {index + 1}</p>
                  <h4 className="mt-1 font-medium text-pearl">{stage.title}</h4>
                  <p className="mt-2 text-sm leading-6 text-stone-400">{stage.detail}</p>
                </div>
              </div>
            </article>
          );
        })}
      </section>

      <section className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <article className="rounded-[1.8rem] border border-white/10 bg-white/[0.045] p-5 md:p-6">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-iris">Proposal review contract</p>
          <h3 className="mt-2 text-xl font-semibold text-pearl">Inspect and adjust before approval</h3>
          <p className="mt-3 text-sm leading-6 text-stone-400">
            When the gate opens, every proposal must show the Personal account role, exact operation and
            label, exact message and thread counts, deterministic criteria, protected/uncertain exclusions,
            redacted examples, safe per-message review metadata, and the immutable selection fingerprint.
          </p>
          {proposal ? (
            <div className="mt-5 space-y-4">
                <div className="grid gap-3 rounded-2xl border border-white/10 bg-black/20 p-4 text-sm sm:grid-cols-2">
                  <p><span className="text-stone-500">Account</span><br />Personal Gmail</p>
                  <p><span className="text-stone-500">Operation</span><br />{proposal.action_type}</p>
                  <p><span className="text-stone-500">Exact label</span><br />{proposal.details.label_name ?? "None"}</p>
                  <p><span className="text-stone-500">Exact messages / threads</span><br />{selectedTokens.length} / {new Set(proposal.details.targets.filter((target) => selectedTokens.includes(target.message_token)).map((target) => target.thread_token ?? target.message_token)).size}</p>
                  <p><span className="text-stone-500">Uncertain included</span><br />{proposal.details.uncertainty_count}</p>
                  <p><span className="text-stone-500">Undo plan</span><br />{proposal.details.undo_action_type ?? "Separate manual recovery"}</p>
                  <p className="min-w-0"><span className="text-stone-500">Selection fingerprint</span><br /><span className="block truncate font-mono text-xs">{proposal.details.selection_fingerprint}</span></p>
                </div>
                <div className="grid gap-3 text-xs sm:grid-cols-3">
                  <div className="rounded-xl border border-white/10 bg-black/15 p-3">
                    <p className="font-medium text-stone-300">Criteria</p>
                    <ul className="mt-2 space-y-1 text-stone-500">{proposal.details.selection_criteria.map((value) => <li key={value}>• {value}</li>)}</ul>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/15 p-3">
                    <p className="font-medium text-stone-300">Exclusions</p>
                    <ul className="mt-2 space-y-1 text-stone-500">{proposal.details.exclusions.map((value) => <li key={value}>• {value}</li>)}</ul>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/15 p-3">
                    <p className="font-medium text-stone-300">Redacted examples</p>
                    <ul className="mt-2 space-y-1 font-mono text-stone-500">{proposal.details.representative_example_tokens.map((value) => <li key={value}>{value}</li>)}</ul>
                  </div>
                </div>
              <div className="flex items-center justify-between gap-3 text-xs text-stone-400">
                <p className="font-medium uppercase tracking-[0.16em]">Complete target review</p>
                <p>{selectedTokens.length} selected · maximum {MAX_LABEL_CANARY_MESSAGES}</p>
              </div>
              <div className="max-h-[38rem] space-y-3 overflow-y-auto pr-1">
                {proposal.details.targets.map((target) => {
                  const selected = selectedTokens.includes(target.message_token);
                  return (
                    <label key={target.message_token} className="block cursor-pointer rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-stone-300 transition hover:border-white/20">
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => setSelectedTokens((values) => selected ? values.filter((value) => value !== target.message_token) : [...values, target.message_token])}
                          className="mt-1"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="break-words font-medium text-pearl">{target.subject}</p>
                              <p className="mt-1 text-xs text-stone-400">
                                {target.sender_display} <span className="text-stone-600">·</span> {target.sender_domain}
                              </p>
                            </div>
                            <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-stone-500">
                              <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
                              {formatReviewDate(target.received_at)}
                            </span>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {target.current_labels.map((label) => (
                              <span key={label.label_token} className="rounded-full border border-white/10 bg-white/[0.055] px-2 py-1 text-[0.7rem] text-stone-300">
                                {label.name}
                              </span>
                            ))}
                          </div>
                          <div className="mt-3 rounded-xl border border-iris/15 bg-iris/[0.05] px-3 py-2">
                            <p className="text-[0.68rem] font-medium uppercase tracking-[0.16em] text-iris">Why selected</p>
                            <p className="mt-1 text-xs leading-5 text-stone-400">{target.selection_reason}</p>
                          </div>
                          <p className="mt-3 font-mono text-[0.68rem] text-stone-600">
                            Message {target.message_token}
                            {target.thread_token ? ` · Thread ${target.thread_token}` : ""}
                          </p>
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <button type="button" onClick={() => void adjustProposal()} disabled={saving || !selectionChanged || selectedTokens.length === 0} className="rounded-xl border border-white/10 bg-white/[0.06] p-3 text-left text-sm text-stone-200 disabled:cursor-not-allowed disabled:opacity-40">Adjust target set</button>
                <button type="button" onClick={() => void rejectProposal()} disabled={saving} className="rounded-xl border border-coral/25 bg-coral/[0.07] p-3 text-left text-sm text-coral disabled:opacity-40">Reject proposal</button>
                <button type="button" onClick={() => void confirmProposal()} disabled={saving || !gate || selectionChanged || !canConfirmProposal(proposal, gate)} className="rounded-xl border border-moss/25 bg-moss/[0.08] p-3 text-left text-sm text-moss disabled:cursor-not-allowed disabled:opacity-40">Confirm exact version</button>
              </div>
            </div>
          ) : (
            <p className="mt-5 rounded-xl border border-white/10 bg-black/20 px-3 py-3 text-sm text-stone-400">
              No executable proposal is present. Review controls remain unavailable at the manual gate.
            </p>
          )}
          {lastOutcome ? (
            <div className={`mt-4 rounded-xl border p-3 text-sm ${lastOutcome.errors.length ? "border-coral/30 bg-coral/10 text-coral" : "border-moss/25 bg-moss/[0.08] text-moss"}`}>
              <p className="font-medium">Result: {lastOutcome.action.lifecycle}</p>
              {lastOutcome.errors.map((value) => <p key={value} className="mt-1">{value}</p>)}
              {lastOutcome.undo_action ? <p className="mt-2 text-stone-300">A separate exact undo proposal is ready for review. It was not executed automatically.</p> : null}
            </div>
          ) : null}
          <p className="mt-4 text-xs leading-5 text-stone-500">
            Confirmation is bound to durable action ID, version, and fingerprint. Changed mailbox state
            invalidates the proposal. Partial or uncertain outcomes are never displayed as success.
          </p>
        </article>

        <article className="rounded-[1.8rem] border border-moss/20 bg-moss/[0.055] p-5 md:p-6">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-moss">Credential-free evidence</p>
          <h3 className="mt-2 text-xl font-semibold text-pearl">Zero mutation calls</h3>
          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3 border-b border-white/10 pb-3">
              <dt className="text-stone-400">Provider mutation calls</dt>
              <dd className="font-mono text-moss">{gate?.provider_mutation_calls ?? 0}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-white/10 pb-3">
              <dt className="text-stone-400">Calendar OAuth</dt>
              <dd className="text-stone-200">Untouched</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-white/10 pb-3">
              <dt className="text-stone-400">Personal Gmail access</dt>
              <dd className="text-stone-200">Read-only</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-stone-400">Automatic undo</dt>
              <dd className="text-stone-200">Never</dd>
            </div>
          </dl>
        </article>
      </section>
    </div>
  );
}
