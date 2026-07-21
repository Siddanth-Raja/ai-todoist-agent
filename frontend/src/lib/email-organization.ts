export const GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify" as const;
export const MAX_LABEL_CANARY_MESSAGES = 10 as const;
export const GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly" as const;

export type GmailMutationGateState =
  | "manual_oauth_required"
  | "label_canary_required"
  | "label_canary_undo_required"
  | "canary_verified";

export type GmailMutationGateStatus = {
  state: GmailMutationGateState;
  required_scope: typeof GMAIL_MODIFY_SCOPE;
  oauth_authorized: boolean;
  label_canary_applied: boolean;
  label_canary_undo_verified: boolean;
  maximum_canary_messages: typeof MAX_LABEL_CANARY_MESSAGES;
  allowed_next_operations: string[];
  calendar_oauth_unchanged: true;
  provider_mutation_calls: number;
};

export type EmailOrganizationTarget = {
  message_token: string;
  thread_token: string | null;
  expected_unread: boolean;
  expected_label_count: number;
  sender_display: string;
  sender_domain: string;
  subject: string;
  received_at: string;
  current_labels: Array<{ label_token: string; name: string }>;
  selection_reason: string;
};

export type GmailReadonlyReviewState =
  | "ready"
  | "empty"
  | "not_configured"
  | "authentication_failure"
  | "provider_failure"
  | "malformed_response";

export type GmailReadonlyReviewLabel = {
  label_token: string;
  name: string;
};

export type GmailReadonlyReviewLabelOption = GmailReadonlyReviewLabel & {
  eligible_message_count: number;
};

export type GmailReadonlyReviewTarget = {
  message_token: string;
  thread_token: string | null;
  sender_display: string;
  sender_domain: string;
  subject: string;
  received_at: string;
  current_labels: GmailReadonlyReviewLabel[];
  unread: boolean;
  selection_reason: string;
  eligible_label_tokens: string[];
};

export type GmailReadonlyReviewSurface = {
  state: GmailReadonlyReviewState;
  configured_scope: typeof GMAIL_READONLY_SCOPE;
  account_role: "personal";
  account_token: string | null;
  source_issue: "SID-230";
  source_label: "INBOX";
  query_summary: string;
  maximum_targets: typeof MAX_LABEL_CANARY_MESSAGES;
  scanned_message_count: number;
  next_page_available: boolean;
  labels: GmailReadonlyReviewLabelOption[];
  targets: GmailReadonlyReviewTarget[];
  exclusions: Array<{ reason: string; count: number }>;
  snapshot_fingerprint: string;
  originating_inventory_fingerprint: string;
  originating_proposal_id: string;
  originating_proposal_fingerprint: string;
  provider_evidence: {
    label_list_requests: number;
    message_list_requests: number;
    metadata_requests: number;
    body_requests: 0;
    full_inventory_scans: 0;
    external_model_calls: 0;
    memory_writes: 0;
    provider_mutation_calls: 0;
  };
  diagnostic_code: string | null;
  executable: false;
  oauth_change_required_before_execution: true;
};

export type GmailReadonlySelectionPreview = {
  snapshot_fingerprint: string;
  selection_fingerprint: string;
  manifest_fingerprint: string;
  originating_inventory_fingerprint: string;
  originating_proposal_id: string;
  originating_proposal_fingerprint: string;
  label: GmailReadonlyReviewLabel;
  targets: GmailReadonlyReviewTarget[];
  exact_message_count: number;
  exact_thread_count: number;
  hand_reviewed: true;
  stale_state_revalidated: true;
  executable: false;
  provider_mutation_calls: 0;
  oauth_change_required_before_execution: true;
};

export function reviewTargetsForLabel(
  review: GmailReadonlyReviewSurface,
  labelToken: string,
): GmailReadonlyReviewTarget[] {
  return review.targets
    .filter((target) => target.eligible_label_tokens.includes(labelToken))
    .slice(0, MAX_LABEL_CANARY_MESSAGES);
}

export type EmailOrganizationProposal = {
  action_id: string;
  version: number;
  fingerprint: string;
  action_type:
    | "gmail_apply_label"
    | "gmail_remove_label"
    | "gmail_archive"
    | "gmail_restore_inbox"
    | "gmail_mark_read"
    | "gmail_mark_unread";
  confirmation_prompt: string;
  details: {
    account_role: "personal";
    message_count: number;
    selection_fingerprint: string;
    originating_proposal_id: string;
    selection_criteria: string[];
    exclusions: string[];
    uncertainty_count: 0;
    representative_example_tokens: string[];
    label_name: string | null;
    canary: boolean;
    canary_undo: boolean;
    hand_reviewed: boolean;
    undo_of_action_id: string | null;
    undo_action_type: string | null;
    targets: EmailOrganizationTarget[];
  };
};

export function removeProposalTarget(
  proposal: EmailOrganizationProposal,
  messageToken: string,
): EmailOrganizationProposal {
  const targets = proposal.details.targets.filter(
    (target) => target.message_token !== messageToken,
  );
  return {
    ...proposal,
    details: {
      ...proposal.details,
      targets,
      message_count: targets.length,
    },
  };
}

export function canConfirmProposal(
  proposal: EmailOrganizationProposal,
  gate: GmailMutationGateStatus,
): boolean {
  if (
    proposal.details.targets.length === 0 ||
    proposal.details.uncertainty_count !== 0 ||
    !proposal.details.targets.every(hasCompleteReviewMetadata)
  ) {
    return false;
  }
  if (gate.state === "label_canary_required") {
    return (
      proposal.action_type === "gmail_apply_label" &&
      proposal.details.canary &&
      proposal.details.hand_reviewed &&
      proposal.details.targets.length <= MAX_LABEL_CANARY_MESSAGES &&
      proposal.details.targets.length <= gate.maximum_canary_messages
    );
  }
  if (gate.state === "label_canary_undo_required") {
    return (
      proposal.action_type === "gmail_remove_label" &&
      proposal.details.canary_undo &&
      proposal.details.hand_reviewed &&
      Boolean(proposal.details.undo_of_action_id) &&
      proposal.details.targets.length <= MAX_LABEL_CANARY_MESSAGES &&
      proposal.details.targets.length <= gate.maximum_canary_messages
    );
  }
  return gate.state === "canary_verified";
}

export function hasCompleteReviewMetadata(target: EmailOrganizationTarget): boolean {
  return Boolean(
    target.sender_display.trim() &&
    target.sender_domain.trim() &&
    target.subject.trim() &&
    Number.isFinite(Date.parse(target.received_at)) &&
    target.current_labels.length > 0 &&
    target.current_labels.every((label) => label.label_token.trim() && label.name.trim()) &&
    target.current_labels.length === target.expected_label_count &&
    target.selection_reason.trim(),
  );
}

export function gateHeadline(state: GmailMutationGateState): string {
  if (state === "manual_oauth_required") return "Manual OAuth approval required";
  if (state === "label_canary_required") return "Label-only canary required";
  if (state === "label_canary_undo_required") return "Canary undo verification required";
  return "Canary verified";
}
