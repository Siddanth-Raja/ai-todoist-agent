import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const today = readFileSync(new URL("../src/app/today/page.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../src/app/projects/[projectKey]/page.tsx", import.meta.url), "utf8");
const chat = readFileSync(new URL("../src/components/chat-panel.tsx", import.meta.url), "utf8");
const evidence = readFileSync(new URL("../src/components/reality-evidence.tsx", import.meta.url), "utf8");

test("Today renders backend reality without adding classification or recommendation heuristics", () => {
  assert.match(today, /todayData\.reality_attention\.map/);
  assert.match(today, /recommendation\.reality/);
  assert.match(today, /obligation\.reality/);
  assert.doesNotMatch(today, /title\.includes|title\.match|classification\s*=/);
  assert.doesNotMatch(today, /score\s*[+\-]=|sort\([^)]*priority/);
});

test("Project Brain keeps pulse, changes, reality totals, and bounded evidence reachable", () => {
  assert.match(project, /Project pulse/);
  assert.match(project, /project\.recent_changes\.total_count/);
  assert.match(project, /project\.reality\.total_count/);
  assert.match(project, /label="Canonical personal reality"/);
  assert.match(project, /RealityEvidenceCard/);
});

test("Chat exposes canonical grounding evidence and provider limitations read-only", () => {
  assert.match(chat, /Shared reality evidence/);
  assert.match(chat, /grounding\.provider_limitations/);
  assert.match(chat, /read only/);
  assert.doesNotMatch(chat, /fetch\([^)]*morning-corrections/);
});

test("shared evidence is accessible without hover and carries correction attribution", () => {
  assert.match(evidence, /<details/);
  assert.match(evidence, /<summary/);
  assert.match(evidence, /effective_correction/);
  assert.match(evidence, /provider_record_id/);
  assert.match(evidence, /source_timestamp/);
  assert.doesNotMatch(evidence, /onMouseEnter|group-hover/);
});
