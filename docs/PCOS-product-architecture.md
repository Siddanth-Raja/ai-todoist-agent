# PCOS approved product architecture

**Decision approved September 14, 2026. Working/unpublished repository documentation pending publication approval.** These are approved product requirements, not claims of implemented or shipped capabilities. The College bridge, capture lifecycle and cross-conversation continuity remain unimplemented. See [current engineering state](PCOS-handoff.md).

## Product promise and surfaces

**Tell PCOS what happened once. It maintains a trustworthy understanding of your life, connects it to what matters next, asks only useful questions, and helps you know when you can stop for now.**

ChatGPT is the primary conversational interface. The PCOS app provides the calm brief, equivalent natural capture, memory inspection/correction and protected-action review. Both consume one shared PCOS state and application service. Cross-conversation continuity requires an actual connected state read; neither surface owns private competing intelligence or assumes access to another transcript.

The default experience contains:

1. One calm opening judgment.
2. Zero or one dominant concern, move or question.
3. Concise upcoming context.
4. What can safely wait.
5. One conversational capture field.
6. Progressive disclosure for evidence, corrections, memory, coverage and actions.

Retrieve before asking; distinguish evidence from interpretation; make correction easy; minimize upkeep. Silence does not prove neglect, attendance, emotion or mastery. No universal Life Score or default grid of domain dashboards. A College detail route is optional and uses the same intelligence.

## Evidence, capture and authority

Conversation is a first-class evidence source alongside permitted providers and a reviewed course baseline. A user's report is authoritative evidence of what they reported, not automatic proof of provider state. Preserve source, subject/account, time, scope, claim type, review/uncertainty state and supersession links. Provider observations, user reports, user corrections and AI interpretations remain distinguishable; source text cannot grant permission.

One explicit, inspectable, revocable initial opt-in enables automatic capture of clearly identified College operational updates as attributable user-reported claims. Record opt-in scope/version. Ambiguous consequential claims remain tentative, await review or trigger one focused question after retrieval. Sensitive narrative requires explicit retention consent. Return a concise durable receipt with correction/undo; uncertain delivery is resolved by status/readback, not a fabricated success message.

Short post-class/end-of-day voice or text dumps must work without recording every class or retaining full transcripts. Preserve raw input, enhanced interpretation and user edits as distinct evidence while available. Retain asked/answered/deferred question dispositions across conversations to avoid repetitive check-ins.

Capture opt-in is not provider-write authorization. Provider mutations retain exact preview, explicit confirmation, stale-preview rejection and existing retry/result safeguards. Undo retracts a PCOS claim; it does not silently reverse a provider action. Dismissal, resolution and verification differ.

## Retention and College state

Raw capture defaults to a seven-day correction window, with earlier removal available. Useful derived context does not expire at day seven: it remains until superseded, resolved, explicitly forgotten or reviewed when its scope ends. Learning needs remain until resolved or reviewed. Scope-end review is not automatic deletion.

Raw-only deletion can preserve reviewed derived context but removes source-text inspection; disclose that limitation. Forgetting retracts dependent claims, summaries and caches and prevents reseeding/resurrection, retaining only necessary non-content audit identifiers. Independently supported facts retain independent provenance. PCOS does not control retention in the conversation host or external providers.

Finished, submitted and learned are independent states, each permitting unknown. “Finished homework, still stuck on substitution” records completion and an open learning need; it does not establish submission or mastery. A corrected deadline neither reopens finished work nor clears a learning need. Stable course/work and provider identity must replace title-only joins. Field revisions, conflicts and corrections remain inspectable; version-bound overrides do not substitute for durable completion claims.

## “Am I good?” contract

Default scope is the rest of today through tomorrow's first commitment, in the user's timezone, including readiness for that commitment. A seven-day lookahead identifies only preparation that must begin within that horizon. If tomorrow is known empty, explicitly bound the assessment through tomorrow's end; missing schedule coverage is not a known empty day. The user may request another horizon.

Read the reviewed cross-course obligation/calendar baseline, relevant preparation and learning needs, plans and material coverage. Account for effort, attendance, travel, rest and uncertainty; a blank calendar does not prove capacity. Optional backlog does not prevent closure.

A gap qualifies or blocks reassurance only if it could materially change this scoped decision. Retrieve alternatives first, then give supported closure, conditional closure with the decisive assumption, or one specific concern/question. Distinguish safe deferral from accepted risk. Explain the scope, decisive evidence and next commitment without making every unknown a new task.

New obligations, corrections, changed plans/capacity, expired material evidence, conflicts or source failures can invalidate the assessment. Recompute on the next relevant read. On-open/on-question checks do not imply continuous monitoring or notification delivery.

## Architecture and component disposition

Conversation, permitted provider evidence and a reviewed baseline enter one College application boundary backed initially by existing SQLite. Shared Personal Reality, Project Brain and recommendations feed grounded reasoning and both surfaces; provider actions remain separately protected.

| Disposition | Decision |
| --- | --- |
| Reuse | Existing canonical project/provider identity, adapters, SQLite ownership, recommendation/time policies, Morning hierarchy, protected pending-action registry/executors and isolation patterns. |
| Extend | Shared conversation lifecycle/provenance, correction/removal, Personal Reality coverage and inputs, field revisions, brief/capture/inspection and reviewed obligation/calendar roles. |
| New within existing boundaries | Versioned College claim/event/receipt contract, transactional application operations, compact context/status reads, durable question dispositions, scoped assessment and least-privilege MCP adapters/authentication binding. No second intelligence or memory database. |

The LLM interprets and explains relevance; the backend enforces identity, authority, opt-in, lifecycle, versions and idempotency. A validated transaction commits event, claim/context changes, canonical version and receipt together. Same event ID/payload returns the original receipt; changed payload conflicts without change. Readback supports at least the acknowledged version. Independent fields may merge; incompatible same-field claims require review. Preserve per-source freshness: one canonical version is not simultaneous provider refresh. Local transactions cannot guarantee exactly-once remote effects.

Expose `get_college_state` and `get_update_status` before separately reviewed `record_college_update`. Reads are bounded and side-effect free; capture and question disposition are explicit commands. Bind principal/workspace/account and College scopes without whole-life access. App capture uses the same service.

Continuous authenticated runtime is required for the connected pilot: persistent SQLite, migrations, managed secrets, backup/restore, restart recovery, environment separation, health/readiness, shutdown and rollback. Runtime design and deployment remain separate. General background scheduling is not an initial pilot prerequisite.

## First vertical-slice acceptance

One course's after-class conversational capture is supported by a reviewed cross-course obligation/calendar baseline, including covered sources, omissions, timestamps and calendar roles. A narrow capture scope cannot silently narrow reassurance to one course.

Acceptance requires:

- One ordinary opted-in ChatGPT update produces a receipt and affects another connected ChatGPT conversation and the existing PCOS brief without duplicate logging. Equivalent app capture follows the same path.
- Messy input preserves attribution/uncertainty; finished/submitted/learned remain separate after corrections. Retrieval precedes one material question, and dispositions prevent repeated questions.
- Optional backlog allows closure; material preparation gaps qualify/block it while irrelevant outages do not. Effort assumptions remain visible.
- Retry, lost response, changed payload, concurrent correction, restart and version readback preserve receipts/state. Provider observations cannot silently erase user reports.
- Raw expiry preserves useful derived learning context. Correction, raw-only removal and forgetting behave distinctly across chats, brief and caches without resurrection; opt-in revocation stops automatic capture.
- The selected hierarchy and inspection/review controls pass responsive/accessibility and explicit product review. Capture performs no provider mutations.
- Isolated synthetic staging precedes a separately authorized real pilot. Keep synthetic data separate from production and the old canary database. API tests, local demos and the section 72 canary alone cannot establish connected acceptance.

The first-slice checkpoint does not complete College Command Center V1. Full acceptance retains email/provider reconciliation, protected actions, security, responsive product review and publication gates. A proposed one-week pilot evaluates repeated questions, corrections, false reassurance and maintenance without a second log; its execution is not authorized here.

## Competitor-derived principles and deferred choices

Competitors are design references and evaluation candidates, not dependencies. Borrow Granola's inspectable transformation of messy conversation and Origin's calm domain summary, a few consequential findings, explanations and deeper exploration. Granola Chat's documented meeting/file scope is not full-life context. Akiflow/Aki already documents personalized memory, MCP and shutdown rituals; these are not unique PCOS claims. Motion, Sunsama, Reclaim and Amie inform scheduling, realistic workload and interaction choices. The approved v3 evidence appendix distinguishes official behavior, marketing and untested assumptions; this decision adds no hands-on competitor claims.

PCOS must demonstrate stronger evidence handling, cross-conversation continuity and lower upkeep. Do not rewrite for feature parity or build commodity scheduling, meeting recording, budgeting, investing, taxes, aggregation or forecasting. Detailed finance remains with a dedicated provider; later PCOS may consume reviewed, attributed attention-level conclusions with coverage/freshness limitations. No universal numerical Life Score is selected.

Defer broad monitoring/notifications, native apps, full domain workspaces and detailed finance. Resolve exact schema/migration/conflict representation at the contract gate, speech/host-retention details at capture, model/prompt selection through evaluation and hosting/auth/secrets/backup operations at runtime. Storage migration requires demonstrated need and separate review.

## Approved roadmap and documentation ownership

The [handoff's section 73](PCOS-handoff.md#73-approved-product-architecture-and-roadmap-reconciliation) records exact issue ownership and dependencies. The approved order is SID-249 → SID-259 contract → SID-151 lifecycle → SID-250 domain state → SID-260 reads → SID-261 capture → SID-147 brief → SID-251 surfaces → SID-156 design → SID-157 runtime → SID-262 staging → SID-252 acceptance. Retained prerequisites and the SID-148 full-milestone branch remain mandatory. SID-149 is deferred; SID-236 retains SID-252, SID-258 and SID-248 blockers. No implementation is started by this approval.

Repository documentation owns engineering truth; Git determines published state. Working changes are visibly labeled working/unpublished until their publication record identifies a commit. Obsidian receives a one-way snapshot from an identified published commit, accompanied by source path, commit, source hash, export time and state. Never overwrite the published mirror with working bytes; a failed export leaves an explicitly stale snapshot. College HQ owns student workflow policy and links to the canonical engineering decision instead of maintaining another engineering roadmap. Project instructions and existing mirrors are unchanged by this reconciliation.

Decision provenance: approved `PCOS-product-architecture-final-proposal.md`, evidence appendix `PCOS-product-architecture-proposal-v3.md` and `PCOS-current-handoff.md` under `/Users/siddanthraja/Desktop/pcos-planning/`, plus the subsequent approved bounded issue packaging. Those planning artifacts remain preserved; their historical approval requests do not override the user's later approval. Research and drift-audit detail remain outside this concise canonical decision.
