import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  applicableCorrections,
  correctionRequestPayload,
  MORNING_SECTION_ORDER,
  providerConfirmationPayload,
  providerPreviewPayload,
  statementPresentation,
} from "../src/lib/morning-brief.ts";


const statement = {
  schema_version: 1,
  statement_id: "statement-1",
  source_reconciliation_id: "reconciliation-1",
  source_reality_item_id: "reality-1",
  evidence_version: "evidence-1",
  section: "attention_today",
  classification: "needs_action",
  status: "needs_action",
  summary: "Concrete obligation",
  reason: "Due today from shared reality.",
  canonical_project_id: "project-1",
  canonical_project_key: "project-one",
  life_area_id: "project-one",
  linked_work_identity: { provider: "linear", provider_record_id: "issue-uuid" },
  provider_identities: [],
  source_evidence_references: ["linear:issue-uuid"],
  source_evidence_summaries: ["Linear says open."],
  source_timestamps: ["2026-08-07T09:00:00-05:00"],
  observed_at: "2026-08-07T09:00:00-05:00",
  freshness: "fresh",
  availability: "complete",
  fact_type: "deterministic_conclusion",
  confidence: "high",
  uncertainty: [],
  temporal: null,
  suggested_action: null,
};

const synthesis = {
  synthesis_id: "synthesis-1",
  evaluated_at: "2026-08-07T09:00:00-05:00",
};


test("Good Morning renders the exact five typed synthesis sections in contract order", () => {
  assert.deepEqual(MORNING_SECTION_ORDER, [
    "changes_since_meaningful_check",
    "attention_today",
    "handled_paused_waiting",
    "project_momentum_constraints",
    "realistic_day_shape",
  ]);
});

test("Must do remains semantically distinct from mismatch and lower-confidence context", () => {
  assert.equal(statementPresentation(statement).label, "Must do");
  assert.equal(
    statementPresentation({ ...statement, classification: "potential_mismatch" }).label,
    "Review mismatch",
  );
  assert.equal(
    statementPresentation({ ...statement, classification: "unknown" }).label,
    "Unknown · evidence incomplete",
  );
});

test("only reality-backed statements expose contextual correction controls", () => {
  assert.deepEqual(applicableCorrections(statement), [
    "already_done",
    "not_today",
    "waiting_on_someone",
    "snooze",
    "wrong_context",
  ]);
  assert.deepEqual(
    applicableCorrections({
      ...statement,
      source_reconciliation_id: null,
      evidence_version: null,
    }),
    [],
  );
});

test("PCOS correction payload binds synthesis, statement, evidence, actor, and idempotency", () => {
  const payload = correctionRequestPayload(
    synthesis,
    statement,
    "already_done",
    "correction-key",
  );
  assert.equal(payload.synthesis_id, "synthesis-1");
  assert.equal(payload.statement_id, "statement-1");
  assert.equal(payload.evidence_version, "evidence-1");
  assert.equal(payload.correcting_actor, "user-primary");
  assert.equal(payload.idempotency_key, "correction-key");
  assert.equal("provider_mutation" in payload, false);
});

test("provider preview and confirmation payloads are separate and exact", () => {
  const previewPayload = providerPreviewPayload(
    synthesis,
    statement,
    "preview-key",
  );
  assert.equal(previewPayload.statement_id, "statement-1");
  assert.equal("proposed_value" in previewPayload, false);
  const confirmation = providerConfirmationPayload(
    {
      schema_version: 1,
      preview_id: "preview-1",
      statement_id: "statement-1",
      synthesis_id: "synthesis-1",
      evidence_version: "evidence-1",
      provider: "linear",
      provider_record_type: "issue",
      provider_record_id: "issue-uuid",
      field_name: "status",
      previous_value: "started",
      proposed_value: "completed",
      provider_revision: "rev-1",
      requested_by_actor: "user-primary",
      created_at: "2026-08-07T09:00:00-05:00",
      expires_at: "2026-08-07T09:10:00-05:00",
      status: "ready",
      diagnostic: null,
      confirmed_at: null,
      result_reference: null,
      request_idempotency_key: "preview-key",
    },
    "confirm-key",
  );
  assert.deepEqual(
    {
      provider: confirmation.provider,
      provider_record_type: confirmation.provider_record_type,
      provider_record_id: confirmation.provider_record_id,
      field_name: confirmation.field_name,
      previous_value: confirmation.previous_value,
      proposed_value: confirmation.proposed_value,
    },
    {
      provider: "linear",
      provider_record_type: "issue",
      provider_record_id: "issue-uuid",
      field_name: "status",
      previous_value: "started",
      proposed_value: "completed",
    },
  );
});

test("Good Morning uses retained revalidation and never recomputes synthesis in the client", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");
  assert.match(source, /useRetainedApiQuery<MorningStateSynthesis>\("\/morning-state"\)/);
  assert.match(source, /refresh failed; showing retained state/i);
  assert.doesNotMatch(source, /score|rankTasks|inferProject|classifyStatement/);
  assert.doesNotMatch(source, /(?:PCOS|Freelance|Nebulo|XO).*(?:rule|classification)/);
});

test("honest no-action and partial-provider states are first-class copy", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");
  assert.match(source, /Nothing urgent needs attention/);
  assert.match(source, /Absence of an urgent item is not being treated as proof/);
  assert.match(source, /Provider limitations/);
});

test("initial provider interaction only previews; exact confirmation is a second action", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");
  const previewIndex = source.indexOf("/morning-provider-reconciliation/preview");
  const confirmIndex = source.indexOf("/morning-provider-reconciliation/confirm");
  assert.ok(previewIndex > 0);
  assert.ok(confirmIndex > previewIndex);
  assert.match(source, /The first step only previews one exact provider record and field/);
});

test("dialog has accessible semantics, keyboard focus handling, and duplicate protection", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");
  assert.match(source, /role="dialog"/);
  assert.match(source, /aria-modal="true"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /event\.key !== "Tab"/);
  assert.match(source, /previewTrigger\.current\?\.focus/);
  assert.match(source, /disabled=\{confirming\}/);
});

test("evidence is reachable without hover and narrow content can wrap", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");
  assert.match(source, /<details/);
  assert.match(source, /Evidence, identity, and uncertainty/);
  assert.match(source, /break-words/);
  assert.match(source, /Evidence version<\/dt><dd className="mt-1 break-all/);
  assert.doesNotMatch(source, /tooltip|group-hover.*evidence/i);
});

test("correction history and reversible PCOS undo remain reachable", async () => {
  const source = await readFile("src/app/morning/page.tsx", "utf8");
  assert.match(source, /Correction history/);
  assert.match(source, /Undo PCOS correction/);
  assert.match(source, /No provider data was changed/);
});

test("mobile navigation keeps full-size touch targets in a contained scroll region", async () => {
  const source = await readFile("src/components/app-shell.tsx", "utf8");
  assert.match(source, /href: "\/morning"/);
  assert.match(source, /overflow-x-auto/);
  assert.match(source, /min-h-14 min-w-16/);
});
