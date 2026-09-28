export type CollegeRecord =
  | { record_type: "identity"; record_id: string; canonical_id: string; identity_kind: string; attributes: Record<string, unknown> }
  | { record_type: "claim"; record_id: string; claim_id: string; subject_id: string; field: string; revision: number; value: unknown; claim_status: string; source_class: string; certainty: string; recorded_at: string; evidence_refs: string[] }
  | { record_type: "conflict"; record_id: string; subject_id: string; field: string; reason: string }
  | { record_type: "coverage"; record_id: string; provider: string; account_id: string | null; availability: string; completeness: string; freshness: string; reason: string; assessed_at: string | null; observed_through: string | null }
  | { record_type: "assessment"; record_id: string; assessment_status: string; assessed_at: string | null; valid_through: string | null; attention_items: unknown[]; result_kind: string | null };

export type CollegeStatePage = {
  schema_version: "college-state-read/1.0";
  status: string;
  assessment_status?: string;
  records: CollegeRecord[];
  pagination: { next_cursor: string | null };
  coverage_expectations: Array<{
    provider: string;
    availability: string;
    completeness: string;
    freshness: string;
    reason: string;
    observed_through: string | null;
  }>;
};

export type CollegeConsent = {
  active: boolean;
  revision: number | null;
  granted_at: string | null;
  revoked_at: string | null;
  sensitive_retention: boolean;
};

export function capturePreferenceCopy(consent: CollegeConsent | null): string {
  if (consent === null) return "Capture preference unavailable. Refresh to check your saved choice.";
  return consent.active ? "On" : "Off. Reports are not sent until you opt in.";
}

export type CollegeContextItem = {
  item_id: string;
  summary: string;
  status: string;
  certainty: string;
  revision: number;
  raw_source_available: boolean;
  asserted_at: string;
};

export type CollegeContext = {
  status: string;
  items: CollegeContextItem[];
};

export type CollegeAcknowledgment = {
  outcome: "applied" | "saved_for_review" | "pending" | "uncertain" | "rejected";
  acknowledgment: string;
  receipt_id?: string;
  receipt_state: string;
  review?: { prompt: string; item_id: string };
};

export function readableCollegeField(field: string): string {
  const part = field.includes(":") ? field.split(":").at(-1) || field : field;
  return part.replaceAll("_", " ");
}

export function readableCollegeValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) return "No recorded value";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([key, item]) => !["id", "hash", "payload", "schema_version"].some((part) => key.includes(part)) && item !== null && ["string", "number", "boolean"].includes(typeof item))
      .slice(0, 4);
    return entries.map(([key, item]) => `${readableCollegeField(key)}: ${String(item)}`).join(" · ") || "Recorded detail";
  }
  return "Recorded detail";
}

export function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    user_confirmed: "Your report",
    provider_observation: "Connected source",
    email_evidence: "Email evidence",
    reviewed_baseline: "Reviewed course baseline",
    assistant_inference: "Interpretation",
  };
  return labels[source] ?? readableCollegeField(source);
}

export function knownPrecommitRejection(status: number): boolean {
  return [400, 401, 403, 404, 409, 422].includes(status);
}

export function collegeClaimDisplay(field: string, value: unknown): { title: string; detail: string; qualification?: string } {
  if (field === "deadline" && value && typeof value === "object" && !Array.isArray(value)) {
    const deadline = value as { value?: unknown; precision?: unknown; timezone?: unknown; kind?: unknown };
    const when = typeof deadline.value === "string" ? deadline.value : "The exact date or time is unresolved";
    const kind = typeof deadline.kind === "string" ? readableCollegeField(deadline.kind) : "recorded";
    const zone = typeof deadline.timezone === "string" ? ` · ${deadline.timezone}` : "";
    return {
      title: "Deadline",
      detail: `${when}${zone} · ${kind}`,
      qualification: deadline.precision === "date"
        ? "Date only; no time of day is established."
        : typeof deadline.value !== "string"
          ? "The timing needs review before relying on it."
          : undefined,
    };
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const observation = value as { kind?: unknown; value?: unknown };
    if (observation.kind === "topic_covered" && typeof observation.value === "string") {
      return { title: "Topic covered", detail: observation.value, qualification: "Reported class coverage does not establish understanding." };
    }
    if (observation.kind === "assessment_observed" && observation.value && typeof observation.value === "object") {
      const check = observation.value as { kind?: unknown; status?: unknown; outcome?: unknown };
      return {
        title: check.kind === "quick_check" ? "Quick check" : "Class assessment",
        detail: check.status === "occurred" ? "Occurred in class" : "Reported class assessment",
        qualification: check.outcome === "unknown" ? "Result was not reported." : undefined,
      };
    }
    if (observation.kind === "announcement_reported" && typeof observation.value === "string") {
      return { title: "Reported announcement", detail: observation.value, qualification: "The date and scope still need direct evidence." };
    }
  }
  return { title: readableCollegeField(field), detail: readableCollegeValue(value) };
}

export function collegeConflictDisplay(field: string, reason: string): { field: string; reason: string } {
  return { field: readableCollegeField(field), reason: readableCollegeField(reason) };
}

export function collegeRecordGroups(records: CollegeRecord[]) {
  return {
    identities: records.filter((item): item is Extract<CollegeRecord, { record_type: "identity" }> => item.record_type === "identity"),
    claims: records.filter((item): item is Extract<CollegeRecord, { record_type: "claim" }> => item.record_type === "claim"),
    conflicts: records.filter((item): item is Extract<CollegeRecord, { record_type: "conflict" }> => item.record_type === "conflict"),
    coverage: records.filter((item): item is Extract<CollegeRecord, { record_type: "coverage" }> => item.record_type === "coverage"),
    assessments: records.filter((item): item is Extract<CollegeRecord, { record_type: "assessment" }> => item.record_type === "assessment"),
  };
}

export function invalidateDependentCollegeDetails(state: CollegeStatePage | null): CollegeStatePage | null {
  if (!state) return null;
  return {
    ...state,
    records: state.records.filter((item) => item.record_type === "identity" || item.record_type === "coverage"),
    assessment_status: "needs_refresh",
  };
}

export function createCollegeReadGate() {
  let generation = 0;
  return {
    begin: () => ++generation,
    invalidate: () => { generation += 1; },
    isCurrent: (token: number) => token === generation,
  };
}

export async function collectCollegePages(
  firstQuery: string,
  fetchPage: (path: string) => Promise<CollegeStatePage>,
  maximumPages = 4,
): Promise<CollegeStatePage> {
  let combined: CollegeStatePage | null = null;
  let cursor: string | null = null;
  for (let page = 0; page < maximumPages; page += 1) {
    const suffix = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
    const response = await fetchPage(`/college/state?${firstQuery}${suffix}`);
    combined = combined ? { ...response, records: [...combined.records, ...response.records] } : response;
    cursor = response.pagination.next_cursor;
    if (!cursor) break;
  }
  if (!combined) throw new Error("College state is unavailable.");
  return combined;
}

// A tab-local delivery journal, never a source of College facts. No API key is stored.
export type PendingCollegeCommand = { path: string; payload: Record<string, unknown>; label: string; expiresAt?: number; retryExpired?: boolean };
export async function collegeDeliveryKey(url: string, apiKey: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([url, apiKey])));
  return `pcos.college.delivery.v1.${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function readCollegeDelivery(storage: Pick<Storage, "getItem" | "setItem">, key: string, now = Date.now()): PendingCollegeCommand | null {
  const raw = storage.getItem(key);
  if (raw === null) return null;
  const value = JSON.parse(raw);
  if (!value || !["/college/update", "/college/surface/consent", "/college/surface/context"].includes(value.path)
      || typeof value.label !== "string" || !value.payload
      || typeof value.payload.command_id !== "string" || typeof value.payload.idempotency_key !== "string") {
    throw new Error("The pending College request cannot be recovered. Do not resubmit it as a new update.");
  }
  if (typeof value.expiresAt !== "number") throw new Error("Pending request expiry is unavailable.");
  if (now >= value.expiresAt && !value.retryExpired) {
    const redacted = { path: value.path, label: value.label, expiresAt: value.expiresAt, retryExpired: true,
      payload: { command_id: value.payload.command_id, idempotency_key: value.payload.idempotency_key } };
    storage.setItem(key, JSON.stringify(redacted));
    return redacted;
  }
  return value;
}

export function writeCollegeDelivery(storage: Pick<Storage, "setItem" | "removeItem">, key: string, command: PendingCollegeCommand | null) {
  // Failure must stop delivery: otherwise a reload could silently lose its identity.
  if (command) {
    const saved = { ...command, expiresAt: command.expiresAt ?? Date.now() + 7 * 24 * 60 * 60 * 1000 };
    storage.setItem(key, JSON.stringify(saved));
    return saved;
  }
  storage.removeItem(key);
  return null;
}
