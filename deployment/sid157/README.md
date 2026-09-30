# SID-157 synthetic deployment preparation — NOT DEPLOYED

Approved baseline: `aa3939a2aed2b884e5871ac178c9abb3f6e6482a`.
This directory prepares the provider-disabled synthetic runtime only. Nothing
installs/enables systemd, creates an account, provisions OCI, starts Tailscale,
opens a port, or changes a firewall. Deployment requires separate authorization.

The primary remains the approved **conditional Oracle Always Free A1** topology:
1 OCPU / 6 GB ARM64, eligible Ubuntu, 50 GB boot + 50 GB attached data in the home
region, one owner/one worker, private Tailscale Serve. It can be independent of
Mac uptime but has no SLA, guaranteed capacity, reclamation exemption or fixed
recovery deadline. Mac fallback fails Mac-independent availability while asleep.
**$0 new recurring infrastructure charges; never upgrade to PAYG.**

## Local synthetic preparation

Use a NEW isolated environment UUID, `synthetic-` actor/workspace and fresh test
password. Do not adopt the old canary, personal DB, `.env`, transport settings,
provider keys, or frozen SID-249 modules. The explicit image import allowlist
excludes all ten SID-249 paths. The runtime CLI disables dotenv before imports;
the fresh-process regression verifies absence of provider/config imports.

The candidate requirements pin the packages exercised locally, including
[Argon2id](https://pypi.org/project/argon2-cffi/25.1.0/) and the
[age Rust binding](https://pypi.org/project/pyrage/1.3.0/). This is not a
hash-locked Linux wheel supply-chain verification. Python 3.14 ARM64 installation,
all native wheels and an immutable base-image digest still require review and a
successful ARM64 build. The Dockerfile is a build-check recipe, not an alternative
running owner; do not publish an image or mount an active truth store into it.

For future local authorized verification, install this requirements file into a
separate test environment. `backend/scripts/sid157_runtime.py --help` documents
explicit `bootstrap`, `empty-recovery`, `run`, `backup`, `sync`, and `restore`
commands. Config JSON is separate from secrets. Private password/signing/identity
files must be mode 0600 and outside the data/vault trees. Never use real credentials.
Normal `run` does not create schemas, a missing DB, course facts, an owner or keys.
`bootstrap` requires an absent directory and leaves a partial failure unready.
There is no in-place migration of personal data in this candidate.

`root` is an environment directory **directly under the actual data mount**;
`require_mount=true` verifies that parent is a mount point. The environment marker
binds UUID, synthetic actor/workspace and schema; files are private. Do not bypass
the mount guard on Linux to make a failed persistent-volume gate appear passed.
Startup refuses unknown versions/missing durable HMAC verifiers; no key regeneration.
All domain writes use the injected `rw` connection factory, DELETE journal,
secure_delete, foreign keys, memory temporaries, FULL synchronous and five-second
SQLite lock timeout. One process flock and a bounded 16-command admission gate
protect the owner; filesystem locks do not fence another VM or volume attachment.

`pcos-synthetic.service` is **preparation only**: one loopback worker, restricted
synthetic OS identity, data mount checks, graceful drain/restart, no provider or
external network access. Its local ciphertext vault is a test adapter on the host,
not an independent backup. Installing it requires the separately approved OS
account, directories, mount and configuration. The network-denial policy must not
be removed merely to make cloud backups work; a real OCI adapter/IAM/network
allowlist requires review. `journald-pcos.conf` is a candidate dedicated-host
volatile 32 MiB/seven-day policy, not a setting applied to this Mac. Review reverse
proxy, Tailscale and OS logs separately. No access/body/query/raw-exception logging.

The local HTTP boundary exposes only owner login/renew/logout, content-free
operations/probes and the explicit College read/capture/review allowlist. Browser
sessions are hashed in the same DB, limited to eight, idle 12 hours/absolute seven
days; only explicit renewal writes access time. Hosted cookies are host-only,
Secure/HttpOnly/SameSite Strict, with exact Host/Origin and CSRF checks. Loopback
HTTP is allowed solely at the synthetic test origin. Direct LAN and developer-key
requests are denied. Account/password reset invalidates all sessions through an
administrative service method; no public signup/recovery endpoint exists. Request
bodies are capped at 128 KiB, login at five attempts/15 minutes, session reads at
120/minute and writes at 30/minute; overload is rejected before submission.

The existing Next.js pages are NOT rewired to this owner session transport. Their
old local developer-key flow remains local development. No legacy Today/Morning,
settings health, `/chat`, provider, confirmation, diagnostics dump, MCP, OAuth or
ChatGPT transport is mounted. ChatGPT-labeled captures are denied on this HTTP
boundary. Assessment submission is denied until the trusted retained-input
assembler and original-request snapshot binding are reviewed; client baseline
hints are not accepted as facts. These explicit gates prevent deployment readiness
or connected acceptance claims. They are not implementations of downstream issues.

## Local backup and recovery commands

The owning runtime can perform raw expiry/session cleanup every 15 minutes, local
vault suppression sync each interval and one daily backup. No provider/academic
scheduler or notifications exist. Backup failure stays pending; raw/privacy
storage failure takes readiness down. CLI backup/sync is offline maintenance: it
cannot acquire an active owner's lock. Never start a second DB writer as a cron job.

The local vault uses SQLite backup API, integrity/foreign-key checks, reviewed
age public-recipient encryption and HMAC-authenticated manifests containing only
UUID/schema/generation/time/kind/ciphertext checksum. Plaintext scratch stays in
private authoritative storage and is removed in a finally block. Removal is not
physical-erasure proof. The runtime holds no age recovery identity; local tests
use new in-memory synthetic identities. Encryption material and independent
manifest-verification key must be recoverable separately from OCI and the vault.
Real Mac Keychain/passphrase/offline record enrollment remains unperformed.

Privacy commands commit existing local erasure/retraction/revocation plus receipt
and a minimal suppression generation in the **same SQLite transaction**, via
receipt triggers (including a successful retry transition). There is no network
inside it. The write gate covers capture consent check through fact/review commit
and serializes with revocation. A previously committed capture remains prior state;
any capture ordered afterward is denied. Raw expiry can downgrade derived review
state while committing deletion, so its `needs_review` receipt also records
suppression. Duplicate commands do not add generations.

Contiguous authenticated history is read back before an acknowledgment is advanced.
The conservative sanitation strategy deletes every managed backup from an earlier
privacy generation; it does not rewrite old data and claim it was clean. Lost
sync replies leave local acknowledgment pending and exact retry settles idempotently.
`backup_sanitation`/`backup_scope` describe **only this local synthetic vault**;
they do not describe OCI, independent Mac/offline copies, host conversations or
browser caches. This adapter has no OCI network, conditional-object or Mac pull
implementation. Generation/source checks plus the single owner are local evidence,
not evidence of concurrent remote object safety.

Rotation retains at most seven daily + one pre-migration copy, each expiring seven
days from original creation. Quarantine does not prolong retention. Local vaults
are capped more tightly at 3 GiB each (two fit the approved combined 6 GiB), with
20 GiB free reserve; metadata and partial/orphan files count. No new storage is
purchased. Mac combined scratch/other copies and OCI hidden multipart/version bytes
still need real accounting. Backup age/pending suppression age remain inspectable.

Historical restore requires a verified, surviving authoritative DB under its
exclusive owner lock and contiguous sync through its current generation. Only an
unexpired current-generation verified backup is eligible. A new isolated directory
and environment UUID are mandatory. Restored sessions/login attempts are removed,
auth generation/password replaced, and capture remains disabled. Original data
keeps its original trusted actor/workspace; an arbitrary new owner mapping is denied.
The candidate deliberately does not implement an offline override for completeness.

Without complete authority/history, historical backups are logically quarantined,
never copied into active storage, even if old signed metadata says clean. Run the
explicit NEW empty-recovery bootstrap instead: new UUID, new credentials, no old
facts/receipts or retry journals, capture disabled. There is no automatic re-enable
endpoint or stale fallback. Re-enrollment and product cache/journal reset remain
reviewed activation gates. Never pass a manually chosen watermark to bypass this.

## Oracle go/no-go — every item UNTESTED here

Record dated evidence for each component. A checkmark requires actual synthetic
results, not this file or the local tests. Stop on the first hard failure; never
upgrade, use credits as a cost claim, fake utilization or create extra free accounts.

| Gate | Required evidence / refusal |
| --- | --- |
| Authorization | Separate owner authorization for synthetic account/setup/provision/deploy. None is granted by this preparation. |
| Account and cost | Standard unupgraded Free Tier; all resource SKUs Always Free in home region; trial-to-free confirmation and zero billable usage independent of credits. Existing paid tenancy/nonzero line is no-go. |
| Whole manifest | A1 1 OCPU/6 GB, eligible image, 50+50 GB volumes/included performance; zero-cost IP/gateway/egress path; no NAT/LB/domain/paid registry/log export or add-on. Recheck current official terms/console at execution. |
| Aggregate quota | All tenancy consumers included. Two possible 1/6 environments use 1,488 OCPU-hours, 8,928 GB-hours in a 744-hour month and 200 GB total volumes. No third recovery VM/extra volume or automatic growth. Staging on demand. |
| Capacity/reclamation | Actual free capacity; source fence/volume survival/replacement runbook. Capacity unavailable or reclaimed with no free replacement is blocked, never an SLA or PAYG workaround. No artificial keep-alive. |
| ARM64/resource fit | Reviewed immutable OS/runtime; successful pinned native-wheel install, Next.js SWC/sharp production build/start and Python runtime; build peak recorded separately; >=20% steady RAM headroom, disk/journal/scratch headroom; ten readers/two writers bounded; ordinary reads <2 s and writes <5 s target. Local Mac tests do not pass this. |
| Private access | Cellular phone + second computer, Mac asleep/offline; HTTPS renewal and unattended reboot; tailnet owner-only grants; no public app/SSH/DB ingress; no Funnel. Exact Host/Origin/CSRF/session/device revocation and direct-network denial. |
| Durable restart | Data mount missing refuses; process/VM restart and synthetic crash around commit; exclusive attachment/fencing, HMAC keys/receipts/consent intact; migration/full-disk/unknown-schema refusal. No provider replay. |
| OCI backup/sanitation | Implement/review narrow private IAM and conditional generation API; no public links, replication/versioning/archive or snapshots; off-volume age ciphertext, authenticated manifests/readback, denial/quota/rate/lost reply/gaps; prune verified before ack; history-loss quarantine. The local filesystem adapter is insufficient. |
| Object budget | Combined Standard objects <8 GB including hidden versions/parts; target <25,000 requests/month and stop retry budget before 40,000; backoff, one batch/15 min; recheck allowance/current pricing. Failure keeps local privacy working, sanitation pending. |
| Independent Mac backup | Authorized synthetic directory writable by real runtime account; <=6 GiB combined incl. scratch, >=20 GiB free; FileVault/sync/Time Machine disclosure; pinned age tooling, Keychain/passphrase/offline recovery record; awake read-only encrypted pull, interrupted/offline catch-up and original-age rotation; decrypt with OCI denied. Existing same-host test vault is not proof. |
| Restore/loss | Isolated eligible-history restore and separately destroyed original/outbox with old-clean manifest refusal; new empty workspace, rotated credentials, disabled capture, old journals denied; no stale Mac failover. Missing history is no-go for historical recovery. |
| Hosted app boundary | Same-origin owner session frontend, environment/auth-bound journal reset/status-before-exact-retry, missing-parent data unknown; local synthetic profile verified. Read-only `/today` uses the retained College brief; `/activity` and `/morning-state` return explicit 503 provider-disabled results; other parent routes are disabled. Private hosted transport remains untested. |
| Assessment | Retained trusted baseline/coverage and SID-151 snapshot bound once to original request, stale-input denial and interrupted receipt recovery. Local explicit cross-course assessment assembles bounded active, nonsensitive College context and retained canonical facts/coverage; calendar baseline/window stay unknown. Fingerprints bind original retry inputs; client hints are rejected. Hosted staging remains untested. |
| Operations | Quiet probes, safe seven-day logs, graceful drain, patch/reboot and schema rollback refusal; raw/session expiry and backup maintenance; no provider/background monitoring. |
| Separate ChatGPT | Verify $0 entitlement/client/tunnel on VM and actual supported MCP/OAuth/PKCE/refresh/revocation plus trusted owner/workspace least-privilege read/status/write. Browser/HTTP/OpenAPI success does not pass MCP or SID-262. |

Go only if the complete synthetic Oracle/private-phone/persistence/OCI-to-Mac
backup and recovery gates pass at $0. A 7–14 day ordinary-use observation can
reveal problems but cannot promise future availability. Unsupported ChatGPT may
leave compute viability separate, while SID-262 stays unpassed. Calendar-enabled
personal production also retains SID-131/provider authorization. No downstream
issue, real pilot, personal-data migration or outside action is authorized here.

## Local frontend integration (preparation only)

Build the existing locked frontend in an isolated clean directory with Node 22:
`npm ci --ignore-scripts --no-audit --no-fund`, then
`NEXT_PUBLIC_PCOS_SYNTHETIC_RUNTIME=1 npm run build`. The build flag selects the
synthetic session boundary and a fixed same-origin `/runtime-api` rewrite to
`http://127.0.0.1:8017`; it does not enable the provider app. Start only on
`127.0.0.1:3017` for the authorized local test and set the synthetic runtime
config origin to `http://127.0.0.1:3017`. Neither command is a deployment. The
original frontend behavior remains the default when the flag is absent.

Login returns an HttpOnly cookie and tab-local CSRF credential. Read-only
`/runtime/session` verifies environment UUID, owner/workspace and auth generation
before child views mount; it neither renews nor replaces CSRF. A new tab without
the CSRF journal requires login. Incompatible/revoked bindings clear retry state;
logout also clears retained reads and invalidates in-flight results. Blocked
browser storage fails closed even after successful server logout.

The bootstrap-only initial synthetic schema now requires the content-free
`runtime_assessment_inputs` table. A prior pre-review synthetic database lacking
it refuses startup; do not silently adopt/migrate it or any canary/personal DB.
Use a fresh isolated bootstrap for this candidate. Supported-version in-place
production migration/rollback remains a separately reviewed deployment gate.
Explicit assessment supports only `{kind: cross_course, subject_ids: []}` with
a bounded seven-day horizon and future expiry. No read triggers an assessment;
unsupported retained sources and provider/calendar baseline remain unknown.
