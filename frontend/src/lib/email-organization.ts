export const GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify" as const;
export const MAX_LABEL_CANARY_MESSAGES = 10 as const;

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
