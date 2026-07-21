import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  GMAIL_MODIFY_SCOPE,
  MAX_LABEL_CANARY_MESSAGES,
  canConfirmProposal,
  gateHeadline,
  removeProposalTarget,
} from "../src/lib/email-organization.ts";

function gate(state) {
  return {
    state,
    required_scope: GMAIL_MODIFY_SCOPE,
    oauth_authorized: state !== "manual_oauth_required",
    label_canary_applied: state === "label_canary_undo_required" || state === "canary_verified",
    label_canary_undo_verified: state === "canary_verified",
    maximum_canary_messages: MAX_LABEL_CANARY_MESSAGES,
    allowed_next_operations: [],
    calendar_oauth_unchanged: true,
    provider_mutation_calls: 0,
  };
}

function proposal(count = 2) {
  return {
    action_id: "action-test",
    version: 1,
    fingerprint: "a".repeat(64),
    action_type: "gmail_apply_label",
    confirmation_prompt: "Apply exact label?",
    details: {
      account_role: "personal",
      message_count: count,
      selection_fingerprint: "b".repeat(64),
      originating_proposal_id: "sid-230-test",
      selection_criteria: ["deterministic evidence"],
      exclusions: ["protected and uncertain excluded"],
      uncertainty_count: 0,
      representative_example_tokens: ["example"],
      label_name: "PCOS/Action",
      canary: true,
      canary_undo: false,
      hand_reviewed: true,
      undo_of_action_id: null,
      undo_action_type: "gmail_remove_label",
      targets: Array.from({ length: count }, (_, index) => ({
        message_token: `message-${index}`,
        thread_token: `thread-${index}`,
        expected_unread: false,
        expected_label_count: 1,
        sender_display: `Synthetic Sender ${index + 1}`,
        sender_domain: "example.test",
        subject: `Synthetic review subject ${index + 1}`,
        received_at: `2026-07-${String(index + 10).padStart(2, "0")}T15:00:00+00:00`,
        current_labels: [{ label_token: "label-inbox", name: "Inbox" }],
        selection_reason: "Grounded synthetic metadata matched the reviewed canary.",
      })),
    },
  };
}

test("manual OAuth gate never permits confirmation", () => {
  assert.equal(canConfirmProposal(proposal(), gate("manual_oauth_required")), false);
  assert.equal(gateHeadline("manual_oauth_required"), "Manual OAuth approval required");
});

test("first approval is limited to a hand-reviewed label canary of ten or fewer", () => {
  assert.equal(canConfirmProposal(proposal(10), gate("label_canary_required")), true);
  assert.equal(canConfirmProposal(proposal(11), gate("label_canary_required")), false);
  assert.equal(
    canConfirmProposal(
      { ...proposal(), action_type: "gmail_archive" },
      gate("label_canary_required"),
    ),
    false,
  );
});

test("every canary target requires recognizable review metadata", () => {
  const missingSubject = proposal();
  missingSubject.details.targets[0].subject = "";
  assert.equal(canConfirmProposal(missingSubject, gate("label_canary_required")), false);

  const incompleteLabels = proposal();
  incompleteLabels.details.targets[0].current_labels = [];
  assert.equal(canConfirmProposal(incompleteLabels, gate("label_canary_required")), false);
});

test("target adjustment removes one redacted target and updates the exact count", () => {
  const updated = removeProposalTarget(proposal(2), "message-0");
  assert.equal(updated.details.message_count, 1);
  assert.deepEqual(updated.details.targets.map((value) => value.message_token), ["message-1"]);
});

test("canary undo is separately gated and must reference the prior action", () => {
  const undo = {
    ...proposal(),
    action_type: "gmail_remove_label",
    details: {
      ...proposal().details,
      canary: false,
      canary_undo: true,
      undo_of_action_id: "action-test",
    },
  };
  assert.equal(canConfirmProposal(undo, gate("label_canary_undo_required")), true);
  assert.equal(
    canConfirmProposal(
      { ...undo, details: { ...undo.details, undo_of_action_id: null } },
      gate("label_canary_undo_required"),
    ),
    false,
  );
});

test("Email approval UI exposes separate adjust, reject, and exact confirm controls", () => {
  const source = readFileSync(new URL("../src/app/email/page.tsx", import.meta.url), "utf8");
  assert.match(source, /Adjust target set/);
  assert.match(source, /Reject proposal/);
  assert.match(source, /Confirm exact version/);
  assert.match(source, /provider_mutation_calls/);
  assert.match(source, /target\.sender_display/);
  assert.match(source, /target\.sender_domain/);
  assert.match(source, /target\.subject/);
  assert.match(source, /target\.received_at/);
  assert.match(source, /target\.current_labels/);
  assert.match(source, /target\.selection_reason/);
  assert.match(source, /this screen cannot request it or start OAuth/);
  assert.match(source, /email\/organization\/actions\/\$\{proposal\.action_id\}\/confirm/);
});
