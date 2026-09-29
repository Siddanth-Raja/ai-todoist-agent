# SID-156 — dependency and privacy-outage review

**Approved narrow decisions retained — documentation publication authorized September 29, 2026. Git history identifies publication.**

The user approved both resolutions below. They are incorporated into the [architecture proposal](PCOS-production-architecture-SID-156.md) and [handoff](PCOS-handoff.md), forming one consistent three-document publication candidate. This addendum retains the exact SID-131 scope and decision rationale; it is not a competing policy or a request to approve these decisions again. Only the approved Linear edge removal/addition was applied and read back; all other relations and issue statuses/descriptions were preserved. The later hard $0 requirement supersedes paid hosting and fixed recovery targets: after comparing free options, the owner has accepted Oracle Always Free A1 as the conditional primary with private Tailscale browser access and encrypted OCI object backups. Mac + Tailscale is the accepted fallback; the existing Mac is the proposed independent encrypted backup destination, not a second live store. ChatGPT/MCP is conditional. SQLite ownership and the approved privacy/dependency policies remain unchanged. The subsequent September 29 approval authorizes documentation publication and gated SID-156 closeout only; implementation remains unauthorized.

## 1. SID-131: move the gate to the capability it actually supplies

### Exact live scope

[SID-131 — Build In-App Google Calendar Reconnect](https://linear.app/siddanths-workspace/issue/SID-131) is To Do. Its description replaces the developer-oriented Google Calendar token-repair workflow with reconnect beginning in PCOS Settings. It owns recovery from legitimate revocation, credential changes and future provider failures. SID-219 owns the distinct seven-day Testing-mode expiration correction; its completion does not implement SID-131.

The current SID-131 acceptance criteria, transcribed from Linear, are:

1. Settings distinguishes disconnected Calendar from an empty Calendar.
2. Invalid or revoked credentials produce a reconnect state.
3. A Reconnect Google Calendar action exists.
4. OAuth can be initiated from the application experience.
5. Successful authorization updates the provider connection.
6. Provider health is rechecked after reconnect.
7. Successful reconnect restores Calendar reads.
8. Calendar write capability is verified where required.
9. The normal reconnect path does not require Terminal.
10. The normal reconnect path does not require manually editing `.env`.
11. Secrets are not exposed to the frontend.
12. The implementation does not rely on a Testing-mode refresh token expected to expire after seven days.
13. Production deployment uses appropriate redirect URIs and secure credential storage.

SID-131 explicitly notes that deployment direction may affect redirect URI and credential-storage decisions. That makes SID-156's design useful input to SID-131, rather than requiring the reconnect implementation before designing hosting.

### Dependency assessment

| Work | Does it require completed SID-131? |
| --- | --- |
| SID-156 hosting, SQLite, browser/MCP auth, retention, recovery and cost planning | **No.** PCOS user authentication and Google Calendar provider authorization are separate. The design selects callback origin and credential-storage requirements without initiating Google OAuth. |
| SID-157 shared runtime composition, persistent storage, migrations, receipts, scoped PCOS login/MCP, backup/restore and operational checks | **No**, with synthetic data and provider access disabled. Its live acceptance criteria require an authenticated persistent runtime, not live Calendar reconnect. |
| SID-157 missing-provider rendering and synthetic invalid/revoked-credential cases | **No.** Test disconnected/unknown rather than healthy/empty, using existing provider interfaces with synthetic inputs. These tests do not satisfy SID-131's real reconnect criteria. |
| SID-262 connected synthetic ChatGPT/app continuity | **No.** It explicitly excludes real coursework, provider access and provider mutations. Use a reviewed synthetic cross-course schedule/obligation baseline. |
| A supported hosted Calendar reconnect and Calendar-enabled personal production experience | **Yes.** This needs the real callback, secure token update, in-app recovery and authorized health/read verification supplied by SID-131. Hosting an API cannot substitute for those criteria. |
| Calendar write readiness | SID-131 verifies capability where required; **actual writes still require the separate provider-action approval path**. Neither completion nor OAuth scope is standing execution permission. |
| Full SID-252 College acceptance | Retain SID-131 as an explicit prerequisite here so this exception cannot silently waive the Calendar readiness requirement previously inherited through SID-156/157. SID-148, SID-262 and other existing gates remain. |

**Approved decision: narrowly bounded exception.** Do not keep all architecture/runtime work blocked behind Calendar reconnect. Do not move SID-131's implementation into SID-157.

**Exact approved graph change — applied and verified:**

- Removed **SID-131 blocks SID-156** (equivalently, remove SID-131 from SID-156's `blockedBy`).
- Added **SID-131 blocks SID-252**. Live readback confirms the edge on both issues and confirms removal on both SID-131 and SID-156.
- Keep **SID-156 blocks SID-157**, **SID-157 blocks SID-262**, **SID-262 blocks SID-252**, **SID-219 blocks SID-131**, and every other existing relation unchanged. Do not add SID-131 as a SID-157/SID-262 blocker, which would defeat the exception.
- Retained explicit architecture/release restriction: **Calendar-enabled personal production activation requires SID-131 completion plus separately authorized provider setup/verification.** This is an activation gate, not permission to create/start another issue now. Issue descriptions were intentionally left unchanged because only the two relation changes were authorized.

The exception permits only otherwise-authorized architecture, runtime implementation and synthetic staging to advance through their existing separate approvals. It does not authorize any of those actions in this review. No production credentials, provider calls, local `.env` import, personal/canary data import or provider writes are enabled by the exception. Blinn remains pending. Existing published local provider capabilities are not being changed. A provider-free real pilot, if desired later, needs its own explicitly reviewed scope; neither this exception nor synthetic acceptance authorizes it. Full College acceptance cannot claim Calendar coverage from fixtures or claim disconnected means empty.

## 2. Off-volume outage (including R2 if ever used): enforce privacy locally; make restoration conservative

### Superseded rule and rationale

The earlier, now-superseded section 7 required an off-volume intent before accepting privacy mutations and rejected them if R2 was unavailable. Under that rule, an otherwise authenticated user **cannot durably revoke capture consent or forget local content during an R2 outage**. Capture may remain enabled and existing content remains present. That is an undesirable coupling of privacy control to backup availability; it should not be described as immediate revocation/forgetting.

### Approved replacement

In the Oracle-primary candidate the off-volume destination is private OCI Object Storage; the existing Mac holds independently pulled ciphertext copies. When the Mac itself becomes the fallback runtime, same-disk copies are no longer independent of its failure. Every R2 outage/recovery reference below applies to bucket/network/quota failure or a disconnected disk. Use verified conditional object generations (atomic file manifests on disk); R2 is not required. “Local” means the authoritative transaction on the VM or Mac, not a second laptop database.

If authentication and the local SQLite store are available, **R2 unavailability must not block capture-consent revocation, local forgetting or raw-content removal/expiry**. Use the existing lifecycle transaction and receipt semantics. In the same local transaction, record minimal non-content suppression/revocation metadata in a durable outbox for later off-volume synchronization. The outbox is recovery bookkeeping in the same database, not another fact store. Adding it is future implementation, not existing capability.

| Operation/state | Required behavior while R2 is unavailable |
| --- | --- |
| Capture-consent revocation | Commit disabled consent and receipt locally; reject future automatic capture on app and MCP paths. Keep prior facts unless separately forgotten. Do not wait for R2 or revoke unrelated read/assessment access. |
| Local forgetting | Atomically apply existing target/dependent erasure/retraction, tombstones and generation invalidation, plus receipt and recovery-outbox entry. Subsequent authorized reads must not expose the forgotten content or stale dependents. |
| Raw removal/expiry | Continue local deletion and exact-time read suppression under existing lifecycle rules. Preserve independently justified structured claims and learning needs. |
| Acknowledgment | Report the committed local outcome accurately: “Capture disabled” or “Forgotten from active PCOS state,” with separate operational status that backup suppression is pending. Do not claim old backups, cloud snapshots, offline browsers or ChatGPT copies were erased. Do not replace `applied` with a new College receipt state. |
| Ordinary process restart, same surviving database | Recover the durable outbox and continue enforcing stored revocations/tombstones. R2 need not be healthy to preserve local privacy. A local restart is not a historical-backup restore. |
| R2 recovery | Upload contiguous suppression/revocation generations idempotently, read back durability, then create a sanitized backup/prune eligible managed copies. Gaps/unresolved outcomes keep affected historical restoration blocked. Do not re-run or undo the locally committed privacy command just to upload its metadata. |
| Local transaction cannot commit | Return failure or uncertainty, never durable success. Stop new automatic capture through the runtime's fail-closed gate until consent storage is trustworthy; this does not claim the requested deletion occurred. A lost response requires status lookup with the original command identity. |

“Immediate” means effective at the local transaction's commit/linearization point, not zero latency or retroactive cancellation. The single-owner write gate must cover the consent check through capture commit and serialize it with revocation; queued captures recheck consent before applying. A capture that committed before revocation remains prior state; a capture ordered after it must reject. Source review confirms the current capture adapter checks opt-in before domain application, so this serialization must be tested in SID-157 rather than assumed from the presence of a single Uvicorn worker. Existing stale-revision/auth checks still apply; R2 outage creates no authority bypass.

No R2 network request belongs inside the SQLite transaction. No get-state/get-status call drains the outbox or mutates privacy state. Keep sync retry/backoff as bounded recovery maintenance, not provider or academic monitoring.

### Total disk loss before synchronization: explicit guarantee limit

Suppose an old backup contains claim X and active capture consent. During an R2 outage the user forgets X and revokes consent; the local database commits both. The only newer suppression records are on that disk. The disk is then irretrievably lost.

**Neither the old backup nor the older R2 fence can reveal those lost operations.** A local receipt may also have been lost. An apparently resolved/latest remote generation does not prove there were no later local privacy commands. Encryption, checksums, retry queues and ordinary backup RPO do not solve this information loss. The system cannot promise both always-available local privacy commands and guaranteed reconstructable suppression history after this combined failure without another independently durable record of every relevant change.

The approved policy favors local privacy availability and **refuses unsafe data restoration**:

1. Every historical restore starts quarantined, without application reads, capture, sessions or provider actions. Never let restored database contents themselves assert permission to go live.
2. Reconciliation needs an authoritative complete history through the last period in which privacy commands were accepted: ordinarily the surviving original database/outbox, or independently durable evidence proving the entire required interval. Do not infer completeness from the newest R2 object, backup timestamp, object hash, a zero pending count inside an old snapshot, elapsed time or the user's recollection. An external clean checkpoint is sufficient only if no later privacy-accepting interval could have occurred; a checkpoint followed by normal operation is not proof.
3. **After total loss without that evidence, treat suppression history as incomplete even if R2 reports no pending fence.** Keep potentially affected old backups unavailable to the live app. Reconstructing selected remembered deletions is not proof that all forgotten targets were covered.
4. Default recovery is a **new empty workspace**, fresh authentication enrollment and capture disabled until a new explicit opt-in. Do not import old claims, raw evidence, summaries, seeds, receipts or browser retry journals into it. Use a new workspace identity so old tokens/commands cannot silently replay into the replacement. Invalidate old access grants/sessions; provider actions stay disabled.
5. Historical recovery may resume only if complete suppression history is recovered and lifecycle reconciliation passes. No “restore anyway” button is part of the accepted recovery path. Quarantined artifacts remain subject to their retention/deletion policy and are not secretly retained forever for troubleshooting.

This guarantees only that the **approved recovery procedure will not knowingly serve unverified old state**; it cannot guarantee physical deletion of inaccessible historical copies, survival of locally acknowledged privacy receipts after disk destruction, or a usable full-data restore. Operator/manual restoration outside the procedure is not covered.

**Free-first recovery expectations:** the previous 24-hour RPO and four-hour RTO are withdrawn. RPO measures data loss, determined by the last eligible verified backup and suppression completeness; RTO measures time to safe service return, dependent on owner, hardware, keys and evidence. Neither has a fixed commitment here. Daily Oracle backup attempts can run while the Mac sleeps; bucket failure, reclamation and unavailable replacement capacity still prevent a recovery guarantee. Mac fallback additionally depends on an awake Mac and connected storage.

**Approved combined-failure exception remains:** disk loss before independent suppression export can require sacrificing all historical state. Quarantine historical backups unless complete suppression history is established; otherwise recover into a new empty workspace with capture disabled. No recovery deadline overrides this rule. Report empty-workspace service recovery separately from historical recovery. Object lifecycle deletion is best effort, and unplugged independent media cannot be sanitized on schedule; residual physical retention requires owner acceptance, and encryption does not prove erasure.

The user accepted this loss-of-history tradeoff. A future requirement for stronger independent durability would need separate architecture and cost review. Reinstating mandatory R2 writes would avoid acknowledging an unrecorded privacy mutation but again denies local forgetting/revocation during outage. It is not the recommended default, and no stronger guarantee is being claimed without such a mechanism.

### Approved acceptance changes incorporated in the proposal

- SID-157: disconnect R2; revoke consent and forget a target; verify durable local receipts, blocked subsequent capture, dependent suppression and retained outbox across a same-disk restart. Race capture against revocation and prove commit ordering.
- SID-157: reconnect R2; prove idempotent outbox synchronization and completeness checks before historical restore. Test missing generations and lost sync responses without changing local receipt identity.
- SID-157/SID-262: take an old backup, accept privacy commands while R2 is disconnected, then simulate destruction of the local database/outbox. Even with a previously “clean” remote fence, attempted restore must remain quarantined. Demonstrate the empty-workspace recovery path and denial of old credentials/retry journals; no invented suppression history.
- Retain existing forgetting/raw-expiry distinctions, no-provider-action checks, backup retention disclosures and all other acceptance gates. This addendum replaces the original “reject privacy mutation when R2 is unavailable” test expectation; it does not silently weaken local receipt or dependent-erasure semantics.

## Approval and verification record

The two decisions are approved and incorporated; neither remains pending:

- SID-131 no longer blocks SID-156; it now blocks SID-252 and remains mandatory before Calendar-enabled personal production.
- Local consent revocation/forgetting proceeds during R2 outages with atomic lifecycle changes, receipt and pending suppression metadata. Incomplete suppression history after disk loss requires quarantined historical backups and a new empty workspace with capture disabled.

The relation mutation was deliberately bounded: add SID-252 to SID-131's blocks while preserving SID-156, verify, then remove only SID-156. Final before/after comparison of SID-131, SID-156, SID-252, SID-157, SID-262 and SID-219 verified exactly the two directed edge changes and their reciprocals. Every other relation in those records, each status and each description matched the pre-change read. No issue was started/closed; no comment or description mutation was performed.

The hosting direction and proposed backup destination are accepted, not pending again. Proposal section 7 specifies seven daily plus one pre-migration copy per environment (seven-day original-age expiry), a 6 GiB total Mac cap with 20 GiB free reserve, age public-recipient encryption, independent key recovery, wake/online catch-up and isolated restore verification. The read-only September 29 check reports 34.41 GiB available; target-directory write access, encryption setup and restore readiness are unverified. No keys or personal content were read or copied.

Mac-offline forgetting is local server success with pending sanitation of Mac copies. On return, synchronize suppression before restore and prune affected/expired copies; never backdate success or prolong retention to make up missed backups. If original/account loss prevents establishing the complete suppression interval, even a decryptable Mac backup stays quarantined and recovery starts empty with capture disabled. Quarantine does not permit indefinite retention. The publication approval includes the stated backup policy and disclosed historical-copy retention limits; no fixed RPO/RTO or physical-erasure guarantee is introduced.

This approved addendum is one of the three documentation publication paths; publication approval does not authorize running the proposed synthetic test. No paid budget is requested; Pay As You Go is prohibited.
This $0 revision makes no Linear changes. The prior approved relation readback remains valid; last verified SID-131/156/157/252/262 statuses are To Do and SID-249 is In Progress. Continuous availability and actual ChatGPT write continuity are not established by this design. Paid hosting is only a future optional upgrade.

Oracle-primary comparison was completed before the working documents were revised. No account, payment, deployment, provider access or Linear call occurred in this revision. The detailed synthetic experiment is proposed only; a capacity failure does not authorize PAYG or artificial keep-alive workloads.

Publication closeout follows exact-path commit/push verification, committed-byte Obsidian handoff export/manifest verification and Linear evidence before SID-156 Done. Oracle go/no-go, Mac encryption/restore and ChatGPT connectivity remain future gates; SID-157 is not started.
