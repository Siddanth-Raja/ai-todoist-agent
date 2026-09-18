# PCOS provider-neutral College contract

**Contract version:** `college-contract/1.0`

**Status:** Schema and ownership approved by Siddanth; documentation-only publication authorized. Git identifies the published revision; implementation remains unstarted.

**Authority:** This document defines the College domain contract that SID-151, SID-250, SID-260, and SID-261 must implement. It does not claim implementation, provider access, or product acceptance.

## 1. Boundary and ownership

ChatGPT is the primary conversational surface. The PCOS app is an equivalent capture, brief, inspection, correction, and protected-action surface. Both must use one PCOS application service and canonical state; neither may infer continuity from private transcript history.

| Owner | Owns | Does not own |
| --- | --- | --- |
| SID-151 | Capture opt-in, bounded shared conversation context, raw/derived lifecycle, question dispositions, correction/removal propagation | College truth, provider records, MCP transport |
| SID-250 | Canonical College identities, claims, revisions, conflicts, coverage, attention projection, event application, receipts | Conversation transcripts, provider records, UI inference |
| SID-260 | Least-privilege `get_college_state` and `get_update_status` reads | Capture writes, synthesis, provider actions |
| SID-261 | Reviewed `record_college_update` capture through the shared application service | Separate persistence, provider mutation, standing approval |
| SID-147 | Today/Morning brief consumption of the shared College attention semantics | Separate College ranking, truth, or capture persistence |
| Providers | Their own records, identifiers, availability, and mutation results | PCOS claims, interpretations, coverage judgments, receipts |

Calendar, Todoist, Personal Gmail, TAMU Gmail, Blinn mail, LMS/iCal, and future providers continue to own their records. PCOS owns normalized attributable claims, reviewed interpretations, field revisions, conflicts, coverage, receipts, and exact links describing why a provider record is relevant. Capturing a fact never grants provider-write authority. Any task or Calendar mutation remains a typed, versioned preview followed by explicit confirmation; stale previews reject.

## 2. Identity

Every identity has a PCOS-issued immutable `canonical_id`, an `identity_status`, and zero or more exact provider references. Provider IDs remain provider-owned and never become canonical IDs.

| Entity | Minimum canonical identity fields |
| --- | --- |
| Institution | `institution_id`, normalized official name, distinguishing campus/system context when needed |
| Term | `term_id`, `institution_id`, academic period/year, start/end when known |
| Course | `course_id`, `institution_id`, subject/catalog code when known |
| Section | `section_id`, `course_id`, `term_id`, section code or reviewed equivalent |
| Work item | `work_item_id`, `section_id` or explicit cross-course scope, kind, stable provider refs/evidence |
| Learning need | `learning_need_id`, subject identity, topic/skill scope, originating evidence |
| Commitment | `commitment_id`, course/cross-course scope, temporal identity, kind |
| Opportunity | `opportunity_id`, organizer/institution scope, temporal identity, source |
| Provider-purpose link | `provider_link_id`, provider/account, record kind/ID, exact purpose, target canonical ID |

`identity_status` is `resolved`, `provisional`, `needs_review`, or `retired`. A match requires a stable provider reference or a reviewed composite key appropriate to the entity. Titles, subjects, display names, and similar text are evidence only: entities are never merged by title alone. Ambiguous, contradictory, or insufficient identity becomes `needs_review`; application must not guess, fan out provider writes, or collapse records. A later resolution links or supersedes provisional identities without rewriting event history.

Provider-purpose links are unique by provider, account, record kind, provider record ID, purpose, and canonical target. The same provider record may support multiple explicit purposes; a purpose link is not ownership transfer or mutation authority.

### 2.1 Reviewed course context and shorthand

SID-151 stores a versioned, authorized, reviewed context binding: `binding_id`, server-bound actor/workspace, canonical term/section IDs, scope, review provenance/time, validity interval, revision, and revocation state. It references SID-250 identities; it creates no competing course identity. Server validation checks access and current validity. A binding may attach to a conversation only through authenticated/platform-attested surface identity; otherwise use an explicitly selected authorized binding for that interaction without treating the surface hint as attested. A chat title or client surface hint cannot create or select a trusted binding by itself. A revoked, expired, mismatched, or missing binding cannot silently default to a course.

Before asking, retrieve the authorized binding, relevant canonical referents and aliases, independent state, field revisions, and prior question dispositions from shared state. Resolve shorthand such as “Calc,” “Topic 4 individual,” and “team” automatically only when exactly one referent is compatible with the reviewed term/section, work kind, and stated context. An alias is a reviewed reference, not title-only identity merging. Keep individual and team work distinct. Zero or multiple compatible referents retain unresolved evidence for review; batch only genuinely necessary identity/date/intent clarifications into one concise question, honoring answered/deferred dispositions. Do not interrupt for optional detail that can safely remain unknown.

The capture adapter obtains expected subject/field revisions through readback; users never supply technical IDs or revision numbers. New subjects use explicit absent revisions and the existing identity rules. A race still follows section 6: do not silently refresh a stale same-field expectation to force an overwrite. In another conversation, retrieve the same authorized state rather than infer continuity from either transcript.

## 3. Claims, evidence, and revisions

### 3.1 Claim source classes

The required source classes are:

- `user_confirmed`: the user directly asserts a fact; authoritative for what the user reported, not provider agreement;
- `user_relayed_instructor`: the user reports an instructor statement; preserve both reporter and attributed speaker;
- `provider_observation`: a bounded observation of a provider-owned record;
- `email_evidence`: bounded message/thread evidence with exact account identity;
- `document_evidence`: bounded document evidence with document identity/version;
- `inferred_interpretation`: a labeled interpretation derived from cited evidence;
- `assistant_suggestion`: a proposed idea or action, never independent evidence.

Every material claim must contain:

```text
claim_id, subject_id, field, value, claim_status,
source_class, source_actor, provenance, evidence_refs[],
asserted_at or observed_at, recorded_at, freshness,
certainty, supersedes_claim_ids[], schema_version
```

`claim_status` is `tentative`, `active`, `conflicted`, `superseded`, `retracted`, or `rejected`. `certainty` is `confirmed`, `probable`, `possible`, or `unknown`, with an optional bounded rationale. `freshness` carries the evidence's observed time, validity/scope horizon when known, and `fresh`, `stale`, or `unknown`; a newer canonical revision does not make old provider evidence fresh. An evidence reference is the smallest sufficient reference or excerpt, not an unnecessary provider dump.

Assistant text can transform, summarize, or suggest from cited evidence, but cannot corroborate that evidence. Corroboration requires an independently sourced claim. Each field has an append-only revision chain. Corrections add revisions and supersession edges; they do not edit history in place. Undo adds a compensating retraction or restoration revision and cannot silently reverse a provider action.

### 3.2 Field-authority matrix

Authority applies to individual fields, not whole sources or events. Capture acceptance does not establish an effective confirmed claim.

| Field | Authoritative evidence and promotion rule |
| --- | --- |
| Own completion, understanding, attendance, intent, personal constraints | User statements own the user's experience and choices; they do not establish provider submission or grade state. |
| Observed submission, grade, provider-record state | Direct LMS/provider records own the observed state within their recorded scope and observation time; a user report remains separately attributable. |
| Official deadline | Direct course-platform, syllabus, or instructor-announcement evidence is required to promote a correction over an existing directly evidenced deadline. Conflicting direct evidence requires review unless explicit supersession resolves it. |
| User-relayed deadline change | Save the report and attributed instructor/source, but keep it tentative/needs-review when direct evidence is missing or conflicts. Do not replace the effective confirmed deadline merely because the user report is newer. |
| Calendar and Todoist record existence/state | Each provider owns only its own record state, not underlying coursework completion, submission, mastery, or official deadline truth. |
| Obligation/requirement | Direct course or instructor evidence establishes official requirements, waivers, or cancellation; user intent establishes personal choices separately. Missing or conflicting requirement evidence stays unknown or under review. |
| Assistant suggestions | Never authoritative evidence; derivations inherit the limitations of their cited support. |

### 3.3 Independent state dimensions

The following dimensions never imply one another:

| Dimension | Values |
| --- | --- |
| Completion | `not_started`, `in_progress`, `finished`, `unknown` |
| Submission | `not_submitted`, `submitted`, `accepted`, `returned`, `unknown` |
| Understanding/mastery | `needs_learning`, `learning`, `understood`, `mastered`, `unknown` |
| Attendance | `planned`, `attended`, `missed`, `excused`, `unknown` |
| Scheduling | `unscheduled`, `proposed`, `scheduled`, `changed`, `canceled`, `unknown` |
| Obligation/requirement | `required`, `optional`, `recommended`, `waived`, `canceled`, `unknown` |
| Commitment attendance intent | `selected`, `unselected`, `undecided`, `unknown` |
| Provider free/busy | `free`, `busy`, `unknown` |
| Provider-record existence | `observed_present`, `observed_absent_in_bounded_read`, `not_checked`, `unknown` |

Deadline is a separate versioned field containing temporal value, timezone, precision, deadline kind, and certainty. “Finished section 2.3 but didn't learn it” means `completion=finished` plus an open learning need; it says nothing about submission. A deadline correction does not reopen completion. A scheduled block proves only scheduling. Absence from an open-task read does not prove completion, submission, deletion, or provider-wide absence.

## 4. Immutable update contract

### 4.0 Client command, stored event, and server receipt

For fact capture, a client submits a versioned command with one or more fact events as an atomic batch. The separate assessment-only operation in section 9.2 carries no fact events. Each event has the following client-owned fields; a batch also has a stable command ID/key and ordered member identities, with the same idempotency rules:

```text
schema_version          = "college-event/1.0"
event_id                = client-issued UUID, stable across delivery retries
idempotency_key         = stable key, scoped server-side to actor and workspace
base_canonical_version  = optional read-snapshot context
expected_revisions[]    = subject ID, field, expected field revision (or absent)
source_surface_hint     = optional unverified client provenance hint
asserted_at/observed_at  = source time
event_type              = one frozen variant below
subject_ref             = canonical or explicitly unresolved identity
payload                 = variant fields
evidence[]              = minimal typed references
certainty               = claimed confirmed/probable/possible/unknown
date_precision          = exact_time/date/month/range/relative/unknown when temporal
supersedes_event_ids[]   = explicit deadline correction links, not lifecycle authority
action_intent           = record_fact/propose_provider_action/no_provider_action
```

`expected_revisions` is required for every field being changed, including explicit `absent` for creation. Unresolved identity or an unknown expected revision retains evidence for review rather than overwriting a field. Client certainty is an assertion; the authority matrix determines effective certainty.

The stored event contains the validated client command plus server-owned `actor_id`, `workspace_id`, `recorded_at`, semantic payload hash, and source identity/verification metadata. The server derives the authenticated actor and binds the authorized workspace from trusted authentication and authorization context. Clients cannot select or spoof either; supplied server-owned fields are rejected. Conversation/surface identity is authenticated or platform-attested where available, otherwise explicitly `unverified`; a client hint never establishes identity or authority.

The server canonicalizes and hashes the client semantic fields, including expected revisions, evidence, and correction targets. Transport IDs/keys and delivery metadata are excluded; server-owned actor/workspace, recorded time, attestation, and receipt metadata are excluded from the client semantic payload hash but retained in the immutable stored event/receipt. Actor/workspace isolation is enforced independently of hashing. Hash equality is transport-payload equivalence, not the semantic-claim matching rule in section 6.

The server receipt separately identifies the command/member events, bound actor/workspace, recorded time and source verification, payload hash, durable state, affected subject/claim IDs, committed canonical version when applicable, review/error references, and lifecycle affordances. A batch commits all validated events, affected claims/context, field revisions, canonical version, and terminal receipt outcome in one local transaction, or no domain change. A prior durable acceptance receipt may exist as described in section 5. Content-bearing history is immutable except for the explicit privacy erasure boundary in section 8.

### 4.1 Frozen variants

| Variant | Minimum payload beyond the envelope |
| --- | --- |
| `deadline_confirmed` | work/commitment identity; temporal value, timezone, precision, deadline kind |
| `deadline_corrected` | target deadline claim/event; replacement temporal value; reason; supersession |
| `completion_submission_recorded` | work identity; explicitly named completion and/or submission dimensions; never infer omitted dimensions |
| `course_progress_recorded` | section/topic identity; explicit `progress` or `session_observation` payload kind as defined below; independent understanding value only if asserted |
| `study_need_recorded` | course/topic identity; need statement; target/readiness date if stated; resolution criteria if known |
| `recurring_commitment_recorded` | commitment identity; recurrence rule or unresolved natural pattern; start/end, timezone, exceptions when known |
| `opportunity_recorded` | opportunity identity; organizer/source; time window; requirements and decision state when known |
| `conflict_recorded` | involved canonical subjects; field/kind; competing claims; materiality; review status |

Applicable variants may explicitly carry the versioned obligation/requirement and attendance-intent fields; omitted dimensions never change. The set of eight fact variants is unchanged; section 4.2 explicitly expands the approved payload of `course_progress_recorded`. Non-deadline corrections, undo, forgetting, and raw removal enter through the separate lifecycle commands in section 8.

Relative dates must also preserve original text, interpretation timezone, anchor instant, and computed interval. If the anchor or meaning is not deterministic, the event remains tentative/`needs_review`; it must not manufacture an exact deadline. `action_intent=propose_provider_action` creates only a proposal for the protected-action system. No event variant directly mutates a provider.

### 4.2 Dated course-session observations

Expand the existing `course_progress_recorded` variant explicitly; do not add a ninth fact variant. Its `progress` payload retains progress measure/unit. Its `session_observation` payload carries a canonical section, a stable session/observation reference under that section, session date or interval, timezone, date precision, and separately attributable observation entries. A date alone is not a unique session identity: multiple meetings on one date remain distinguishable; unresolved session identity stays provisional. “Today” uses the assertion's reliable time and user timezone, not delivery time; missing anchors remain uncertain under section 4.1.

Each entry has a stable observation ID, kind (`topic_covered`, `assessment_observed`, `announcement_reported`, `attendance_reported`, or `coordination_blocker`), normalized reported value, source class/actor, asserted/observed time, evidence references, certainty, and optional exact affected work/commitment/topic IDs. Entries are separately revisioned fields under the subject; omitted entries do not retract prior observations. Assessment entries preserve kind (including quick check), occurrence/planned status as reported, and unknown outcome/grade. Announcement entries preserve attribution and uncertainty without manufacturing deadlines or requirements. Attendance is recorded only when asserted; reported class content does not prove attendance. Coordination blockers record the affected work/scope, reported impediment, and resolution state (`open`, `resolved`, or `unknown`) only as supported.

Reported observations remain distinct from derived importance. Covering a topic does not establish mastery; a quick check does not establish a grade; an exam warning does not establish an exam date, scope, or required task. Any inferred significance is a separately labeled interpretation with evidence and rationale, evaluated in section 9.1. Completion/submission and learning needs continue to use their existing variants and independent dimensions; a mixed update can yield multiple events in the existing atomic batch. This explicit payload expansion is included in the approved contract; subsequent semantic changes require review under section 11.

## 5. Receipts and idempotency

### 5.1 Durable server receipts

| State | Meaning and retry rule |
| --- | --- |
| `received` | Command durably accepted; no domain success implied. Query status. |
| `applied` | Atomic local transaction committed; includes canonical version and affected IDs. May reference an already effective equivalent claim without a new claim revision. |
| `needs_review` | Evidence/review transaction committed, but disputed fields were not promoted to resolved truth. |
| `rejected` | Known validation, authority, identity, key, or concurrency rejection; no requested domain update. |
| `retryable_failure` | Server established no domain commit and a transient failure; same ID/key/payload may be retried. |

Receipt identity is stable; status transitions append immutable records rather than rewriting prior outcomes. `duplicate` is a delivery disposition returning the original receipt and its current durable outcome, not a new durable state. `outcome_unknown` is not a durable local receipt state. Unauthorized requests can be rejected before persistence; responses must not disclose another actor/workspace's receipt.

Within the authenticated actor/workspace, each accepted event/key has one receipt identity. The same event ID or key with equivalent canonical payload returns that receipt. Changed semantic content yields `idempotency_payload_conflict`, no domain change, and preserves the original receipt. An existing event with a new unused key may bind that key as an alias to the original receipt; keys already bound to another event cannot be reassigned. Batch retries preserve the original batch and member identities. Distinct event IDs and keys retain distinct receipts even when section 6 resolves them to one effective claim.

### 5.2 Client-observed outcomes and lookup

The client observes `receipt_observed`, `known_rejection`, or `outcome_uncertain` (timeout/lost HTTP or tool response). A lost response does not establish whether the server accepted or committed the command. Query `get_update_status` with the original ID/key in the authenticated scope before any resend:

- A found receipt returns its recorded state: `received` means wait/query; `applied` or `needs_review` means a committed local outcome; `rejected` means a known rejection; `retryable_failure` permits same-identity retry.
- `not_found` means no durable receipt exists in the authorized store at the lookup snapshot. It is not proof an in-flight request cannot later commit. A bounded resend with the exact original ID/key/payload is safe only through the transactional unique-ID/key boundary that serializes concurrent acceptance; never create a new identity to retry uncertainty.
- Lookup failure/unavailability leaves client uncertainty unresolved; do not blind-retry or claim failure/success.

Provider execution has a separate action receipt and recovery/reconciliation protocol. These local College commands do not execute providers. Neither a local fact receipt nor local `not_found` establishes whether a separately authorized provider action occurred; uncertain provider execution must be reconciled before retry.

### 5.3 Side-effect-free reads

`get_college_state` and `get_update_status` return honest previously recorded state, receipt history, versions, and coverage only. They do not import, initialize, acknowledge, refresh providers, update checkpoints, mutate coverage, process queues, or execute actions. Missing/uninitialized state is reported as such without initializing it. Reads do not renew evidence freshness or resolve pending work; SID-260 owns these guarantees and their side-effect tests.

## 6. Deterministic reconciliation

Reconciliation is field-specific and uses identity, authority, evidence independence, asserted/observed time, freshness, certainty, supersession, and expected subject/field revisions. Arrival order is never a truth rule.

- **Corrections:** a valid correction supersedes only the cited field revision after authorization and field-authority validation; a correction label alone cannot override direct deadline evidence. Unmentioned dimensions remain unchanged.
- **Credible conflicts:** incompatible, credible same-field claims become `conflicted` and `needs_review` unless an explicit correction or deterministic authority rule resolves them. Preserve both.
- **Stale provider observations:** may remain historical evidence but cannot erase a newer supported claim. They lower coverage/freshness and may trigger revalidation.
- **Concurrent changes:** compare expected subject/field revisions transactionally. Disjoint-field changes may merge; an unrelated global canonical-version advance never rejects a safe update. `base_canonical_version` supplies optional snapshot context only. A stale same-field write becomes conflict/review unless an explicit supported correction rule applies: an equivalent claim may be linked without a field write, or a correction targeting the current revision may pass the field-authority rule. Arrival time and a stale correction target grant no override; no last-write-wins.
- **Corroboration:** independently sourced compatible evidence may raise certainty. Repeated copies, forwarded duplicates, assistant restatements, and two conversations relaying the same underlying assertion are not independent corroboration.
- **Semantic duplicates across transport identities:** match only resolved canonical subject, field, normalized value/temporal scope, and attributable underlying assertion/source identity. Equivalent claims with different event IDs/keys retain both immutable events, distinct receipts, and all evidence references, linked to one effective claim revision and one canonical subject. Evidence/receipt linkage may advance the global version without creating another effective field revision. Repeated source copies do not increase corroboration. Never match by title alone; uncertain equivalence stays separate for review.
- **Unresolved identities:** retain evidence under a provisional subject and block unsafe merging/provider proposals until reviewed.
- **Date-only/relative dates:** retain precision. A date-only deadline is not silently assigned a time. Relative language is anchored as specified in section 4.1 or left tentative.
- **Completed work plus later metadata:** deadline, title, provider-link, or schedule changes revise only those fields; completion remains finished unless separately corrected.

## 7. Coverage and confidence

Coverage is recorded per provider/account and relevant scope. It is not inferred from item count.

| Typed dimension | Allowed values | Meaning |
| --- | --- | --- |
| `availability` (access/setup) | `healthy`, `unavailable`, `pending`, `unknown` | Healthy means the recorded access/read succeeded, not that scope was complete or remains fresh; pending means setup/consent/approval incomplete; unavailable means access cannot be used. |
| `completeness` | `complete`, `partial`, `truncated`, `unknown` | Complete applies only to declared bounds; partial covers some expected scope; truncated records a known limit; unknown makes no completeness claim. |
| `freshness` | `fresh`, `stale`, `unknown` | Evaluated at the recorded assessment under an explicit freshness policy, independently of access and completeness. |

Each coverage record supplies all three dimensions separately; slash-combined enum values are invalid. Retain `checked_at`, `observed_through`, scope/bounds, omission reason, and freshness policy. No read means null check/observation times, not fabricated timestamps; a setup assessment is not a mailbox check. Reads expose recorded assessment time and policy without refreshing coverage.

Current Blinn coverage is `availability=pending`, reason `administrator_approval`, `completeness=unknown`, `freshness=unknown`. `availability=unavailable` with that reason is also valid if recorded access is unavailable; never encode the two together. No mailbox check has occurred. Blinn must appear explicitly and never be interpreted as empty, checked, healthy, complete, or silently omitted. TAMU, Personal Gmail, Calendar, task, provider document, and conversational evidence remain usable on their own merits.

Confidence is decision-scoped. A missing source qualifies or blocks advice only when evidence from that source could materially change the specific conclusion. Irrelevant gaps do not prevent supported reassurance. A material Blinn gap must be named as the decisive limitation; no whole-College completeness claim is allowed.

## 8. Capture, correction, retention, and removal

Automatic capture is permitted only after one explicit, inspectable, revocable opt-in for clearly identified College operational updates. Store opt-in scope, version, grant time, and revocation. Revocation stops future automatic capture; it does not silently delete prior state. Fact capture never authorizes provider reads or writes beyond separately granted scopes.

Ambiguous consequential statements stay tentative/`needs_review` or trigger one focused question after bounded retrieval. Persist asked, answered, and deferred dispositions so another conversation does not repeat the question. Sensitive narrative requires explicit retention consent. Ordinary tutoring questions, explanations, practice, hypothetical examples, and requests to solve coursework are not durable College events unless the user separately states an operational update or explicitly asks to retain one.

Raw conversational content means transcript text, audio, screenshots, and large source excerpts. It expires under the seven-day raw-retention policy unless separately retained, and may be removed sooner. Reviewed derived context persists until superseded, resolved, explicitly forgotten, or reviewed at scope end; learning needs persist until resolved or reviewed.

Minimal structured attestation is distinct from raw conversational content. It retains authenticated actor/workspace, source class, asserted/observed time, canonical subject and field, normalized value, event/receipt identity, source availability and verification metadata, and non-content provenance needed to establish that the user/provider actually asserted the fact. For a clear, valid, opted-in operational update, this retained attestation remains inspectable evidence of the authenticated user's normalized assertion. Routine raw-content expiry must not erase or downgrade the durable structured claim. Attestation establishes the assertion within the existing field-authority rules; it does not promote a user-relayed deadline to direct instructor evidence or establish provider agreement.

`remove_raw_evidence` deletes raw content, not automatically the derived fact. Mark the removed raw source unavailable while preserving the separate availability and verification status of retained structured attestation. Downgrade certainty/review status only when removed context was required to support the interpretation, the normalized claim cannot be justified from retained attestation, the source is retracted, contradicted, or explicitly forgotten, or independent retention/authority rules require review. If an ambiguous/inferred interpretation loses its only supporting context and retained attestation cannot justify it, certainty becomes `unknown` and review is required; independent inspectable support sustains only the confidence it warrants. Explicit forgetting retracts the targeted claim and unsupported dependents rather than merely lowering confidence. Correction and undo preserve append-only audit history.

### 8.1 Authenticated lifecycle commands

SID-151 owns separate versioned `college-lifecycle/1.0` commands: `correct_claim` (non-deadline corrections), `undo_update`, `forget_claim`, and `remove_raw_evidence`. They are outside the eight College fact variants and use the same transactional application service and receipt/idempotency boundary as fact capture. SID-250 owns atomic canonical application; SID-261 exposes reviewed capture/lifecycle affordances without a second persistence path. Official deadline corrections retain their fact variant and authority rule.

Each command includes stable command ID/key, exact target claim/event/evidence IDs, expected subject/field revisions, bounded reason/scope, and replacement value/evidence only where applicable. Server-bound actor/workspace authorization must cover every target and dependency; client-supplied identity cannot grant authority. Ambiguous targets require review before mutation. Same identity/payload returns the original receipt; changed payload rejects. Undo names the exact update and adds a compensating revision, respecting subsequent revisions and current authority instead of blindly restoring an obsolete value.

The service traverses the recorded dependency graph through claims, derived context, summaries, question premises, recommendations, projections, and caches. Correction recomputes dependents; forgetting retracts dependent unsupported content; raw removal updates evidence availability and confidence as above. All affected canonical changes, tombstones, receipt outcome, and projection/cache invalidation commit atomically. Readers cannot observe a new canonical version with stale dependent content; cache generation fences make old versions unreadable until recomputation. Failed transactions expose no partial retraction or invalidation. Receipts identify affected/redacted targets and the committed version without retaining forgotten content. Privacy erasure removes content-bearing event/evidence/receipt material where necessary, retaining only non-content immutable audit/tombstone metadata; ordinary corrections preserve history.

“Forget that” retracts the targeted claim and every dependent summary, projection, cache, question premise, and recommendation. Independently supported facts remain with their independent provenance. A non-content tombstone may retain only opaque event IDs, lifecycle times, and dependency/retraction markers necessary to prevent duplicate replay or startup reseeding. It must not retain plaintext, reconstructable content, or an unsalted/raw content hash that can practically reveal low-entropy forgotten text. Prefer opaque event IDs; use keyed/non-reversible fingerprints only where replay prevention genuinely requires them and they do not practically reveal forgotten content. Reads and rebuilds must honor tombstones so forgotten claims cannot resurrect.

### 8.2 Mixed conversational extraction

Within a current capture opt-in and its authorized scope, extract clear operational assertions into minimal structured claims without per-message confirmation. Segment the user's own assertions from surrounding tutoring, hypotheticals, quotations, pasted source text, and assistant suggestions; those surrounding materials must not be relabeled as user assertions. An explicitly relayed announcement can be attributable evidence under its actual source class, not independent direct instructor verification. Preserve negation, uncertainty, date precision, and the distinction between individual and team work. “Submitted” as a user report does not become a verified LMS submission or grade; “needs work” does not by itself diagnose lack of understanding.

Retrieve context and revisions first (section 2.1). Clear portions may be captured while consequential ambiguity remains tentative/needs-review or receives a focused, batched clarification. Do not infer an operational update from merely asking how to solve a problem. Minimal capture is subject to sensitive-retention consent and the raw/structured-attestation distinction above. Capture success requires a durable `applied` receipt, or a durable `needs_review` receipt explicitly described as saved for review, not confirmed truth. `received` means pending; timeout means client uncertainty and status lookup. A conversational acknowledgment alone is never evidence of persistence.

### 8.3 Transient situational context

SID-151 owns bounded situational records, separate from durable College claims: `context_id`, server-bound actor/workspace, asserted time, scope, normalized limitation, `expires_at`, expiry basis, affected commitment/plan IDs (or explicitly unresolved references), resolution state (`unresolved`, `resolved`, or `unknown`), provenance/evidence, consent scope, and revision/receipt identity. Store only the actionable limitation, minimizing sensitive narrative and honoring retention consent. “Forgot my iPad” and “printer unavailable” can constrain the present plan without becoming permanent personal facts or verified provider-wide outages.

Use an explicitly stated end or an applicable reviewed context-expiry policy; preserve its basis. Without either, limit reliance to the current interaction and do not durably carry it into another conversation; clarify only if future reliance is material. An expiry policy must be bounded and inspectable, not invented by the assistant. Context creation/correction/resolution uses authenticated, idempotent SID-151 context writes through the shared transactional service with durable receipts and dependent projection invalidation; these are not extra College fact variants and grant no provider authority.

Expiry ends permission to rely on the limitation as current; it does not assert resolution, device recovery, or printer availability. Keep expiry separate from resolution state. Any still-relevant plan whose feasibility depended on that context becomes unverified until supported; do not claim either that the old limitation persists or that the plan is now feasible. A recorded projection has a validity boundary no later than the expiry of context it relies on. After that boundary, reads may expose it as historical/out-of-validity with its recorded timestamps, but must not recompute, mutate context, or present it as a current assessment. SID-250 recomputes through its authorized write/assessment path; no scheduler or downstream implementation is authorized here. Retention/removal and forgetting continue to follow section 8.

## 9. Scoped closure contract

“Am I good?” defaults to the user's timezone and covers the rest of today through tomorrow's first commitment, including readiness, travel, rest, and required preparation. If tomorrow is verified empty, state that the horizon extends through tomorrow's end. Missing schedule coverage is not an empty day. A seven-day lookahead contributes only preparation pressure that must begin within that horizon.

Before reassurance, read the reviewed cross-course obligation/calendar baseline and relevant:

- confirmed/tentative deadlines and readiness requirements;
- independent completion, submission, learning, attendance, and scheduling state;
- commitments, conflicts, travel/buffer, capacity, and rest;
- existing tasks/plans without treating them as proof of work;
- provider/account coverage, freshness, omissions, and question dispositions.

Obligation/requirement is a versioned field with authority and provenance, independent of completion and attendance intent. `required` unfinished work contributes attention when due or preparation must begin within the horizon; `optional` and `recommended` work may be offered but do not block reassurance by themselves. `waived` and `canceled` obligations contribute no outstanding required work. `unknown` is never defaulted to required or optional: qualify closure or ask for review only when its resolution could materially change the conclusion. Explicitly selected optional work may still create a personal commitment or capacity constraint without becoming an official requirement. Optional ENGR bonus-work backlog therefore does not itself block closure.

Attendance intent and provider free/busy are independent: a selected commitment consumes its known time and buffers even when its provider record is `free`; an unselected opportunity reserves no time. Undecided/unknown intent may qualify advice if material, without inventing a reservation. Optional backlog never prevents closure. Return supported closure, conditional closure with the decisive assumption, or a specific concern/question. A material unknown qualifies or blocks reassurance; irrelevant uncertainty is disclosed only when useful and does not manufacture work. The answer must state the assessed horizon, decisive evidence, coverage limitation if material, and next commitment.

### 9.1 Shared course and cross-course attention projection

SID-250 owns one recorded College attention projection with course-scoped and cross-course views of the same canonical inputs and ordering rules. SID-260 exposes recorded results via side-effect-free reads; SID-147 consumes these semantics for Today/Morning briefs, and conversational surfaces render them without maintaining independent rankings or truth. A read may select a recorded scope/window; it cannot generate a new assessment, refresh providers, acknowledge changes, or advance a cursor. If no suitable recorded assessment exists, report that limitation and the available recorded evidence rather than invent current assessed importance.

Each projection records its ID/schema/rule version, canonical input version, authorized scope/term/sections, `assessed_at`, `valid_through`, timezone, explicit horizon, coverage dimensions/bounds/omissions, and baseline/window used. Each attention item includes canonical subject/field revision, category, concise reason, evidence references, authority/certainty, occurrence time and recorded change version/time, requirement state, due/readiness interval and precision if known, dependencies, material unknowns, and applicable transient-context references. Expired inputs or material changes invalidate dependent assessments; generation fencing and side-effect-free read rules remain in force.

Categories include relevant changes (effective field revisions, new attributable observations, corrections/retractions, blocker or coverage changes that affect the selected scope), outstanding required obligations, preparation pressure, unresolved learning needs, coordination blockers, and material unknowns. Equivalent transport copies add no repeated change alert or independent corroboration. Reported session topics can appear as a concise course update; claimed importance must cite an explicit consequence or be labeled an inference. Optional/recommended work never becomes required through ranking; waived/canceled work does not contribute outstanding obligations. A cross-course view deduplicates by canonical attention subject/revision, retaining links to every affected course.

Order deterministically using the recorded assessment time and horizon: (1) current conflicts or blockers affecting a selected commitment or required work within the horizon, including overdue required obligations; (2) remaining required obligations and supported preparation that must begin within the horizon; (3) material unknowns that could alter those conclusions; (4) learning needs and coordination blockers without established in-horizon urgency; (5) other relevant changes and optional/recommended opportunities. Within each band sort by earliest supported action-needed boundary, then earliest due/readiness interval lower bound, then canonical subject ID and field/revision. Unknown temporal keys sort after known ones within their band; tied cross-category items use category name as the final stable key. An item may carry multiple categories but appears once in its highest applicable band. Ambiguous dates retain their intervals; ordering is not a claim of exact urgency. A material unknown must remain visible in a concise answer even if lower-priority details are omitted.

Preparation pressure needs a supported readiness deadline and duration/lead-time evidence. Unknown duration, travel/buffer, or available capacity stays explicit; it cannot yield an invented confident start time, workload fit, or “you are good” plan. Offer conditional advice or one material clarification instead. Use section 9's default closure horizon unless an explicit bounded request (such as today's Calc session) supplies another horizon. Cross-course conclusions still require the reviewed cross-course baseline and material coverage; a course-only answer cannot imply whole-College reassurance.

“Since last interaction” requires an explicit authorized cursor or recorded interaction baseline bound to actor/workspace, scope, and last acknowledged canonical change position/time. SID-151 owns the baseline's lifecycle; creating or advancing it is a separate authenticated, receipt-backed context write authorized by an explicit acknowledgment or reviewed interaction policy, never a side effect of reading or answering. A timestamp or chat title from an unverified surface is not an authorized cursor. SID-250 retains occurrence and recorded change times so late-reported observations are shown as newly recorded without misdating the class session. When no baseline exists, use and state an explicit bounded time window: for “today,” local day start through the requested assessment time; otherwise the applicable recorded horizon. Do not call this “since we last talked.” If the matching recorded window is unavailable, disclose that gap. Reading the same state twice preserves the cursor and eligible changes.

Conversational output should state the few decisive changes/concerns and any material qualification, with inspectable detail carrying evidence, coverage, horizon, and assessment time. A short answer may summarize recorded items, but must not silently add an independent importance judgment, plan, or completion claim. No projection or conversational suggestion executes tasks, Calendar changes, messages, or provider actions.

### 9.2 Assessment-production lifecycle

SID-250 owns assessment production through the shared application service. Accepted relevant fact/context changes atomically invalidate affected projections and either recompute within bounded local work or durably enqueue recomputation with the triggering change position and affected scope. This includes corrections, retractions, and accepted SID-151 context changes; irrelevant changes and equivalent transport retries do not require duplicate work. Pending work is never silently treated as a current assessment. This is a local assessment lifecycle, not authorization for general background monitoring or provider access.

The specified application command `record_college_update` owns an explicit versioned operation `request_assessment`, separate from its fact-capture operation. This names an approved contract operation, not an already implemented capability or a ninth fact variant. Its request contains a stable command ID/idempotency key, authorized course/cross-course scope, bounded horizon/timezone, and requested baseline/window where applicable; actor/workspace and assessment time are server-bound. It carries no fact events, replacement claims, acknowledgment, or context-resolution instruction. An explicit user request for a current brief authorizes this bounded local assessment of already stored, authorized evidence; fact-capture opt-in is not required for assessment alone. Existing authorization, payload-conflict, durable receipt, and timeout/status-lookup rules apply. Replaying the same request returns its existing result/status; a later genuinely new brief request uses a new command identity.

ChatGPT invokes the `request_assessment` operation through the reviewed `record_college_update` adapter when a current brief needs a new assessment. The app's explicit current-brief request invokes the same application operation directly. SID-261 owns the command adapter boundary, SID-250 the assessment service, and SID-147 consumes its resulting projection; no issue dependencies change. Both surfaces may first read recorded state and reuse a suitable valid assessment. They must dispatch a distinct authorized command if the assessment is missing, invalidated, or expired, rather than hiding recomputation inside a read. Earlier architecture wording about recomputing “on the next relevant read” is realized as this explicit command followed by readback, never as a side effect of either read tool.

Expose recorded assessment work status `queued`, `running`, `ready`, or `failed`, together with request/trigger identity, scope, input versions, assessment ID when ready, and bounded failure/retry information. Assessment validity is separate: publish `assessed_at`, `valid_through`, and recorded invalidation markers. A read can report that the recorded validity interval has elapsed without persisting a status change or processing work. Command receipt `received` means pending; `applied` means the derived assessment and terminal receipt committed atomically, not that new facts were captured. A known no-result failure follows the existing failure/retry rules. `ready` means a completed assessment, which may conclude conditional closure or insufficient evidence; it does not mean healthy coverage or reassurance.

Compute against a consistent authorized fact/context snapshot and server assessment time, retaining source observation/check times and provenance. Before publishing, verify relevant input versions, authorization, and expiry boundaries; a racing change invalidates the candidate and causes bounded recomputation/requeue, not publication as current. Store the derived projection, validity boundaries and receipt together without revising factual claims or interaction cursors. Status and result readback use `get_update_status` and `get_college_state`; both remain side-effect-free. While queued/running or after failure, return honest pending/failure status and any explicitly historical assessment, never fabricated current success.

Assessment permission authorizes no provider refresh, new factual claim, acknowledgment/cursor advance, or provider action. Recompute significance and feasibility from stored evidence only: missing/stale evidence stays visible with its original timestamps, and cannot become fresh because `assessed_at` is new. Time-dependent freshness may be assessed as worse under the existing policy, never renewed by local computation; provider coverage/checkpoints are not refreshed. Expired situational limitations cease to be current inputs without being marked resolved. A current assessment is possible when remaining evidence supports the requested horizon; otherwise the current result explicitly states the decisive evidence/capacity gap.

## 10. Deterministic scenarios

| Scenario | Accepted evidence | Resulting claims/state | Review, receipt, and prohibited side effects |
| --- | --- | --- | --- |
| “I finished section 2.3, but I did not learn it.” | `user_confirmed`, asserted now | work completion `finished`; submission `unknown`; open learning need/understanding `needs_learning` | `applied`; no task completion, LMS change, or mastery claim |
| “The ENGR deadline moved from September 7 to September 9.” | user report; prior deadline claim if resolvable | Save attributable Sept 9 report as tentative; existing directly evidenced Sept 7 remains effective confirmed deadline pending direct correction evidence; completion unchanged | `needs_review` without direct evidence; promote Sept 9 only with direct course-platform/syllabus/instructor-announcement evidence resolving the correction and date/term; saving the report is not deadline confirmation; no Calendar/task write |
| “My professor mentioned something may be due next week.” | `user_relayed_instructor`; original relative text | tentative possible deadline window, exact work identity/date unresolved | `needs_review` or one focused question; no exact deadline or reminder manufactured |
| “I need to study chemistry before Thursday's lab.” | `user_confirmed`; resolved course/lab/relative anchor if available | open chemistry learning need and preparation target before lab; no completion/mastery claim | `applied` or identity/date `needs_review`; no study block or task created |
| “Can I attend this engineering event without falling behind?” | opportunity details plus closure inputs and coverage | opportunity stays separate; decision advice uses schedule, deadlines, learning needs, capacity, and material coverage | read-only advice; conditional/blocked if a material gap exists; no RSVP, Calendar, or task write |
| Completed assignment, then provider deadline changes | direct course-platform deadline correction evidence plus existing completion revision | deadline revision updates; completion remains `finished`; submission/learning unchanged | `applied`/corroborated deadline; no reopen or duplicate task |
| Blinn unavailable; TAMU and conversation usable | explicit Blinn coverage plus healthy/fresh evidence elsewhere | Blinn availability `pending`, completeness/freshness `unknown`, administrator-approval reason; other claims remain usable with source-specific confidence | reassurance qualified only if Blinn could materially change it; never infer empty/healthy Blinn |
| Same update from two ChatGPT conversations | same authenticated actor/workspace, different event IDs and keys, equivalent same-source claim with resolved subject identity | two immutable events and receipts, retained evidence links, one effective claim revision and one canonical subject | both receipts identify the effective claim; no false corroboration or title-only merge; same-ID/key retry separately returns the original receipt as delivery disposition `duplicate` |
| Same idempotency key with altered content | same actor/key, changed semantic payload | no domain change | `rejected: idempotency_payload_conflict`; caller must use a new key for a genuinely new intent |
| User says “forget that” | authenticated removal command and dependency graph | target and dependent projections retracted; independent evidence retained; non-content tombstone prevents replay | `applied`; dependent cache/read-model generations atomically invalidated before readback; no provider deletion and no resurrection from transcript, cache, or seed |
| Optional ENGR bonus work remains | directly supported `obligation=optional`; required readiness met; relevant coverage adequate | bonus backlog remains open without blocking scoped closure | supported reassurance; no automatic task completion or requirement promotion |
| Selected commitment marked free | user intent `selected`; known interval/buffers; Calendar record `free` | consumes capacity despite provider free/busy; unselected opportunity reserves none | closure considers time conflict; no Calendar write |
| Raw evidence removed | (a) routine raw expiry after a clear, valid, opted-in user-confirmed completion with retained structured attestation; (b) removal of the only context supporting an ambiguous/inferred interpretation | (a) raw source unavailable; structured completion remains active with unchanged certainty, supported by inspectable attestation; (b) retained attestation cannot justify interpretation: certainty `unknown`, review required; dependents recomputed/invalidated | atomic lifecycle receipt; raw removal alone does not forget the fact; explicit forgetting retracts the target and unsupported dependents |
| Spoofed actor/workspace | client command supplies server-owned actor/workspace or unauthorized target | reject before domain application; trusted auth binding cannot be overridden | no cross-workspace readback, event application, or receipt disclosure |

**Specification verification:** All ten original scenarios and four added rows were re-evaluated against this revised contract; the cross-conversation row covers the additional different-ID semantic-duplicate case. These are deterministic specification walkthroughs, not executed implementation acceptance. The deadline scenario requires direct correction evidence; retaining its report alone never promotes September 9. Ownership remains SID-151/250/260/261 as in section 1.

### 10.1 Conversational continuity walkthroughs

These specification cases assume valid capture opt-in, authorization, and reliable date anchors where stated; missing prerequisites follow the final row. They do not claim executed acceptance or live data.

| Case | Result and evidence boundary | Receipt, readback, and interruption behavior |
| --- | --- | --- |
| “Calc covered continuity today; there was a quick check and an exam warning.” | Resolve Calc via reviewed binding; record dated topic, assessment occurrence, and reported announcement as separate session observations. Grade, attendance, exam date/scope, and importance are not inferred. | `applied` for clear attributable observations; missing consequential exam detail remains unknown/reviewable. No unnecessary confirmation or invented deadline. |
| “Topic 4 individual is submitted but needs work; team started, no group chat.” | Retrieve distinct individual/team referents. Preserve user-reported submission without promoting LMS state; preserve “needs work” as reported unresolved work concern, not inferred mastery/completion. Team completion is `in_progress`; no group chat is an open coordination blocker. | Existing fact variants plus expanded session observation retain independent fields with receipt(s). Ask once only if referents or a consequential meaning remain ambiguous after retrieval; no team message or provider mutation. |
| “We covered derivatives; I’m lost on definition problems.” | Record dated topic observation plus a distinct user-confirmed learning need scoped to definition problems. Coverage of derivatives does not imply understanding; no submission change. | Atomic capture receipt; shared projection includes the learning need, with urgency only if supported. Tutoring that follows is not itself captured as fact. |
| “I forgot my iPad and the printer is unavailable.” | Store minimal SID-151 situational limitations with asserted time, scope, affected plan/commitment and supported expiry basis. Do not infer missed attendance or incomplete work. | Context receipt if retained with consent and valid expiry; otherwise current-interaction use only. Unknown alternatives/capacity do not produce a confident replacement plan. |
| Another conversation: “Anything important from Calc today?” | Retrieve authorized course binding, dated observations and recorded attention projection. Return reported topics/check/announcement and supported concerns, with assessment time, today window and material coverage limitations. | Reads remain side-effect-free. If a current assessment is needed, the explicit brief request authorizes section 9.2’s separate assessment command and readback; no recapture, provider refresh, acknowledgment or cursor advance. |
| Temporary context expires with no evidence of resolution | Stop treating iPad/printer limitations as current; resolution stays unresolved/unknown. Dependent plan feasibility and old projection validity are not restored by expiry. | Reads disclose out-of-validity assessments without writes; new assessment requires the authorized path. No false recovery claim or automatic repeated question. |
| No attested course binding or last-interaction cursor | Retrieve authorized reviewed bindings/referents first. An explicitly selected authorized binding can scope this interaction; an unverified hint alone cannot. If none or several remain, ask one course/term clarification and keep capture unresolved. | Do not ask for IDs/revisions. With no cursor, state the bounded today/recorded-horizon window; never claim “since last interaction,” create a binding, or advance a cursor just by reading. |

Review result: the seven cases preserve deadline authority, independent dimensions, durable receipts, provider-action boundaries, and raw-expiry/structured-attestation rules. The original fourteen scenario rows remain applicable. SID-151/250/260/261 keep their approved responsibilities; SID-147 is a consumer of shared attention semantics, with no dependency changes or implementation start.

### 10.2 Expired assessment with no intervening capture

1. The stored assessment has passed `valid_through`; no new fact or context capture has occurred. The user asks, “Give me a current College brief.” A state read reports the expired assessment and recorded evidence/status without mutating anything.
2. The surface invokes `record_college_update` with operation `request_assessment`, a new request ID/key, and the authorized bounded scope/horizon. This explicit brief request supplies assessment permission only. The shared service records a receipt and runs bounded local assessment or exposes queued/running status.
3. Assume retained structured completion claims and the stored schedule/deadline evidence still support the new horizon under their existing freshness policies. SID-250 assesses them at the current server time, excludes expired transient limitations without claiming resolution, and verifies the input snapshot before atomically publishing a new projection and `applied` receipt. A plan depending on an unresolved expired limitation remains unverified unless independent evidence supports it.
4. ChatGPT or the app reads the ready result and returns a current, evidence-supported brief with its assessment time, horizon, evidence references and material coverage qualifications. No capture, provider refresh, new factual assertion, acknowledgment or provider action was needed. If stored evidence is stale or insufficient instead, the newly produced assessment states that gap and provides only supported/conditional conclusions; recomputation never manufactures freshness or reassurance.

Specification check: a time-expired assessment can be replaced without an intervening capture, through an explicitly authorized assessment command. Pending/failure states remain visible, same-request retries preserve receipts, and both read tools retain their side-effect-free guarantees. This is a specification walkthrough, not runtime acceptance.

## 11. Approval and change control

Siddanth explicitly approved the revised schema and ownership rules, freezing `college-contract/1.0` as the downstream implementation contract. Any semantic change to identity, authority, state independence, event variants, idempotency, reconciliation, ownership, coverage, retention/removal, or closure inputs requires a new contract version and explicit review. Additive display wording does not change the contract; loosening safety or evidence rules always does.

Documentation-only publication is authorized for this contract and `docs/PCOS-handoff.md`, including commit, normal fast-forward push, remote verification, and committed-byte handoff export with a commit/hash manifest. SID-259 may close only after those publication checks pass and evidence is recorded on the issue. This approval authorizes no provider authentication, provider reads/writes, migrations, services, MCP tools, UI implementation, or start of SID-151 or any downstream issue. SID-249 remains externally paused with its implementation preserved. Git and the export manifest establish publication state; the SID-259 issue records the verified commit and final closeout.
