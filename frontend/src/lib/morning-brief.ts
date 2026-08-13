import type {
  MorningCorrectionType,
  MorningSectionId,
  MorningStateSynthesis,
  MorningStatement,
  ProviderMutationPreview,
} from "./api";

export const MORNING_SECTION_ORDER: MorningSectionId[] = [
  "changes_since_meaningful_check",
  "attention_today",
  "handled_paused_waiting",
  "project_momentum_constraints",
  "realistic_day_shape",
];

export const MORNING_SECTION_COPY: Record<
  MorningSectionId,
  { eyebrow: string; detail: string }
> = {
  changes_since_meaningful_check: {
    eyebrow: "What changed",
    detail: "The few recent changes worth knowing.",
  },
  attention_today: {
    eyebrow: "Attention today",
    detail: "Concrete obligations lead; uncertainty and review items remain distinct.",
  },
  handled_paused_waiting: {
    eyebrow: "Under control",
    detail: "Handled, intentionally paused, waiting, and protected upcoming work.",
  },
  project_momentum_constraints: {
    eyebrow: "Project pulse",
    detail: "Shared Project Brain momentum, constraints, coverage, and uncertainty.",
  },
  realistic_day_shape: {
    eyebrow: "Shape of the day",
    detail: "Commitments and usable capacity, without manufacturing more work.",
  },
};

export function statementPresentation(statement: MorningStatement) {
  if (statement.classification === "needs_action") {
    return {
      label: "Must do",
      tone: "border-coral/35 bg-coral/[0.09]",
      badge: "bg-coral/15 text-coral",
      priority: "primary",
    } as const;
  }
  if (statement.classification === "potential_mismatch") {
    return {
      label: "Review mismatch",
      tone: "border-gold/30 bg-gold/[0.07]",
      badge: "bg-gold/15 text-gold",
      priority: "review",
    } as const;
  }
  if (statement.classification === "waiting") {
    return {
      label: "Waiting",
      tone: "border-sky-300/20 bg-sky-300/[0.055]",
      badge: "bg-sky-300/10 text-sky-200",
      priority: "supporting",
    } as const;
  }
  if (statement.classification === "already_handled") {
    return {
      label: "Already handled",
      tone: "border-moss/25 bg-moss/[0.055]",
      badge: "bg-moss/10 text-moss",
      priority: "supporting",
    } as const;
  }
  if (statement.classification === "upcoming_not_actionable") {
    return {
      label: "Upcoming · not today",
      tone: "border-white/10 bg-white/[0.035]",
      badge: "bg-white/[0.06] text-stone-300",
      priority: "supporting",
    } as const;
  }
  if (statement.classification === "no_meaningful_change") {
    return {
      label: "No meaningful change",
      tone: "border-white/10 bg-white/[0.03]",
      badge: "bg-white/[0.06] text-stone-400",
      priority: "context",
    } as const;
  }
  return {
    label: "Unknown · evidence incomplete",
    tone: "border-iris/25 bg-iris/[0.055]",
    badge: "bg-iris/10 text-iris",
    priority: "context",
  } as const;
}

export function applicableCorrections(
  statement: MorningStatement,
): MorningCorrectionType[] {
  if (!statement.source_reconciliation_id || !statement.evidence_version) {
    return [];
  }
  const result: MorningCorrectionType[] = ["wrong_context"];
  if (
    statement.classification === "needs_action" ||
    statement.classification === "potential_mismatch" ||
    statement.classification === "waiting"
  ) {
    result.unshift("already_done", "not_today", "waiting_on_someone", "snooze");
  } else if (statement.classification === "upcoming_not_actionable") {
    result.unshift("not_today", "snooze");
  }
  return [...new Set(result)];
}

export function correctionOutcome(type: MorningCorrectionType): string {
  return {
    already_done:
      "Records an attributable PCOS confirmation. It does not complete the provider record.",
    not_today:
      "Protects the item until the next local day boundary. It does not mark it complete or irrelevant.",
    wrong_context:
      "Disputes this association while preserving the original evidence for review.",
    waiting_on_someone:
      "Records a PCOS waiting state without inventing a deadline or changing provider fields.",
    snooze:
      "Temporarily suppresses this statement for one hour; the underlying evidence stays intact.",
  }[type];
}

export function correctionLabel(type: MorningCorrectionType): string {
  return {
    already_done: "Already done",
    not_today: "Not today",
    wrong_context: "Wrong context",
    waiting_on_someone: "Waiting on someone",
    snooze: "Snooze 1 hour",
  }[type];
}

export function correctionRequestPayload(
  synthesis: MorningStateSynthesis,
  statement: MorningStatement,
  correctionType: MorningCorrectionType,
  idempotencyKey: string,
) {
  const parameters: Record<string, string> = {};
  if (correctionType === "snooze") {
    parameters.snooze_until = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  }
  return {
    synthesis_id: synthesis.synthesis_id,
    evaluated_at: synthesis.evaluated_at,
    statement_id: statement.statement_id,
    evidence_version: statement.evidence_version,
    correction_type: correctionType,
    parameters,
    correcting_actor: "user-primary",
    idempotency_key: idempotencyKey,
  };
}

export function providerPreviewPayload(
  synthesis: MorningStateSynthesis,
  statement: MorningStatement,
  idempotencyKey: string,
) {
  return {
    synthesis_id: synthesis.synthesis_id,
    evaluated_at: synthesis.evaluated_at,
    statement_id: statement.statement_id,
    evidence_version: statement.evidence_version,
    requested_by_actor: "user-primary",
    idempotency_key: idempotencyKey,
  };
}

export function providerConfirmationPayload(
  preview: ProviderMutationPreview,
  idempotencyKey: string,
) {
  return {
    preview_id: preview.preview_id,
    evidence_version: preview.evidence_version,
    provider: preview.provider,
    provider_record_type: preview.provider_record_type,
    provider_record_id: preview.provider_record_id,
    field_name: preview.field_name,
    previous_value: preview.previous_value,
    proposed_value: preview.proposed_value,
    confirming_actor: "user-primary",
    idempotency_key: idempotencyKey,
  };
}
