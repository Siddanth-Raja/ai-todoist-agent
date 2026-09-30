# SID-157 — local implementation publication candidate

September 30, 2026. **Complete local publication candidate; unstaged, unpublished, not deployed or accepted.**
HEAD, tracked `origin/main` and the live remote `refs/heads/main` all match
`aa3939a2aed2b884e5871ac178c9abb3f6e6482a`. Read-only `git ls-remote origin
refs/heads/main` confirmed this during publication preparation on September 30,
2026 (remote check completed before the 13:58:29 UTC evidence readback). No fetch,
ref mutation, staging, commit or push occurred. Recheck the remote before any
separately authorized publication.
The approved SID-156 proposal/addendum still equal committed bytes. The working
handoff, approved proposal/addendum, product architecture, frozen College contract,
README/backend instructions and implementation-pass procedure governed this work.
The current continuation request explicitly authorizes updating the working handoff; its new local evidence is unpublished.

Live SID-157 requirements were retrieved before coding. It was moved from To Do
to In Progress when authorized work began, with ordinary progress comment
`dd2c7e88-4a9f-4a2f-bfc8-3b69aa5cf840`. Its acceptance criteria and directed
blocking dependencies remain unchanged. The September 29 checkpoint evidence is comment
`bdea4fa3-0ac7-44cc-8fae-04e0ebafee77`. The initial progress comment introduced
an unintended reciprocal related link to the frozen provider issue; only that
link was removed. Final live readback verified the original eleven downstream
blocks, the sole architecture blocker, no related links on this issue, and all
other provider-issue relations/status preserved. This implementation is authorized by the
owner's current request; historical “unstarted” documentation is not a deployment
permission. No downstream issue is started or accepted.

## Availability reconciliation

“Continuously available” retains the Mac-independent intent, **conditionally**:
Oracle Always Free A1 can serve while the Mac sleeps if the actual free capacity,
private access, persistent storage, auth/restart and backup gates pass. It promises
no uptime percentage, replacement capacity, reclamation exemption or fixed RPO/RTO.
The accepted Mac/Tailscale fallback is unavailable while its Mac sleeps/offline and
cannot silently satisfy that criterion. $0 new recurring infrastructure charges
remains mandatory; PAYG, trial-credit substitution and paid workarounds are prohibited.
This wording is recorded in the ordinary progress update, not a changed dependency
or a waiver of connected acceptance.

## Candidate scope

| Files | Review purpose |
| --- | --- |
| `backend/app/runtime_store.py` | Exclusive SQLite owner, environment/mount/schema guards, explicit new bootstrap, injected non-initializing connections, bounded write gate, startup interruption/expiry recovery, transactional privacy outbox triggers |
| `backend/app/runtime_auth.py` | Argon2id synthetic owner, hashed DB sessions/CSRF, idle/absolute expiry, persistent login limit, eight-session limit, explicit renewal/logout and administrative reset |
| `backend/app/runtime_api.py` | Provider-disabled College composition, cookie/Host/Origin/CSRF boundary, allowlisted transport, body/admission/rate limits, quiet probes/logs and operational retention/backup maintenance |
| `backend/app/runtime_backup.py` | SQLite snapshot/integrity, age encryption, authenticated manifest/contiguous local vault history, original-age rotation/capacity, pending sanitation, isolated restore and quarantine |
| `backend/app/storage.py` | Inject exclusive runtime connection factory while preserving original local dotenv/bootstrap path outside synthetic mode |
| `backend/app/college_read_api.py`, `backend/app/college_capture_api.py` | Lazy local settings seam and explicit synthetic composition without provider/config module import |
| `backend/app/college_reads.py`, `backend/app/college_surface_api.py` | Shared read-only scoped resolver for SID-151 review/consent receipts and existing SID-250 receipts; additive `college-context-status/1.0` envelope with no invented canonical version; existing broad context authorization preserved |
| `backend/scripts/sid157_runtime.py` | Explicit synthetic config/secret-file/bootstrap/run/backup/sync/isolated recovery commands; loopback only, no deployment actions |
| `backend/tests/test_sid157_runtime.py` | New isolated identity/data/key tests; ASGI HTTP auth/capture/status, real process crash, privacy/race/restart, encryption/rotation/restore/loss and provider-import boundaries |
| `deployment/sid157/requirements.txt` | Separate pinned synthetic dependencies, leaving existing local/provider dependencies unchanged |
| `deployment/sid157/Dockerfile.arm64-check` | ARM64 build-check preparation with explicit source allowlist excluding all ten frozen provider paths; immutable image/native-wheel build gate remains |
| `deployment/sid157/pcos-synthetic.service`, `journald-pcos.conf`, `runtime-config.example.json` | Uninstalled one-worker loopback/mount/network/logging configuration and new synthetic identity placeholders |
| `deployment/sid157/README.md` | Concrete operational/recovery procedure and Oracle $0 go/no-go matrix; every external gate explicitly untested |
| `backend/app/runtime_integration.py` | Side-effect-free retained College parent projection; explicit cross-course assessments with server-assembled bounded context, immutable content-free retry fingerprints and stale-input denial |
| `frontend/next.config.ts`, `src/app/layout.tsx`, `src/app/today/page.tsx`, `src/components/app-shell.tsx` (all under `frontend/`) | Opt-in same-origin synthetic transport/session boundary, narrow navigation and honest provider-unavailable presentation; default development mode preserved |
| `frontend/src/components/runtime-session-boundary.tsx`, `frontend/src/lib/runtime-session.ts` | Owner login/reload/logout, cookie/CSRF access, authoritative environment/owner generation binding and in-flight response invalidation |
| `frontend/src/components/college-review.tsx`, `frontend/src/lib/settings.ts`, `api.ts`, `use-retained-api-query.ts`, `retained-query-store.ts` | Existing consent/capture/privacy/status/exact-retry integration; incompatible journal and retained query clearing; no client provider key in synthetic transport |
| `frontend/tests/runtime-session.test.mjs` | Environment mismatch, cookie/CSRF transport, revoked access, stale completion and blocked-storage regressions |
| `docs/PCOS-handoff.md` | Authorized working continuity evidence; no publication or issue completion |
| This review record | Unpublished review scope/evidence and limitations |

Exact publication candidate inventory (**32 paths**: 15 modified tracked files,
17 new untracked files; 12 backend, 12 frontend, six deployment-preparation and two
documentation paths). The ten frozen paths are excluded and must remain unstaged:

```text
backend/app/college_capture_api.py
backend/app/college_read_api.py
backend/app/college_reads.py
backend/app/college_surface_api.py
backend/app/runtime_api.py
backend/app/runtime_auth.py
backend/app/runtime_backup.py
backend/app/runtime_integration.py
backend/app/runtime_store.py
backend/app/storage.py
backend/scripts/sid157_runtime.py
backend/tests/test_sid157_runtime.py
deployment/sid157/Dockerfile.arm64-check
deployment/sid157/README.md
deployment/sid157/journald-pcos.conf
deployment/sid157/pcos-synthetic.service
deployment/sid157/requirements.txt
deployment/sid157/runtime-config.example.json
docs/PCOS-SID-157-implementation-review.md
docs/PCOS-handoff.md
frontend/next.config.ts
frontend/src/app/layout.tsx
frontend/src/app/today/page.tsx
frontend/src/components/app-shell.tsx
frontend/src/components/college-review.tsx
frontend/src/components/runtime-session-boundary.tsx
frontend/src/lib/api.ts
frontend/src/lib/retained-query-store.ts
frontend/src/lib/runtime-session.ts
frontend/src/lib/settings.ts
frontend/src/lib/use-retained-api-query.ts
frontend/tests/runtime-session.test.mjs
```

There is one store and dependency graph; the legacy/provider app is never mounted.
No existing/canary database or provider credential is reused. Fresh-process tests
verify that frozen config/main/email modules and provider network clients are not
imported by the runtime graph. Normal startup cannot create a missing DB, seed
facts, grant consent or regenerate fingerprint keys. Unknown schema and missing
keys fail closed. This candidate supports explicit NEW synthetic bootstrap and
isolated recovery; it does not perform an in-place personal-data migration.

The active root must be directly under the verified persistent mount in the Linux
configuration. flock is process ownership, not fencing across two VMs; exclusive
attachment and old-owner fencing remain external deployment gates. Threads remain
serialized for consent-check-through-commit, including captures saved for review.
DELETE/secure_delete/FULL/foreign keys/memory temporaries are enforced on writers.
Accepted commands commit durable receipts; read/status/session verification do not
renew sessions, dispatch assessments, drain suppression or initialize storage.

Privacy receipt triggers atomically record suppression for local revoke/forget/raw
removal/expiry, including `needs_review` raw-expiry receipts and committed lifecycle
retry transitions. No off-volume request is required for local success. Local vault
sanitation is separate and pending on failure; older generations are conservatively
pruned before sync acknowledgment. Its diagnostics explicitly name local synthetic
scope, never independent Mac/OCI erasure. Historical offline/conversation/browser
retention is not claimed erased.

age encryption uses pinned mature Rust bindings, not a custom encryption design.
The local vault is intentionally a filesystem test adapter. It is not an OCI IAM,
conditional object-generation, cross-host transfer or independent Mac backup client.
At most seven daily and one pre-migration copies survive, each <=seven days from
original creation; two 3 GiB caps fit the approved combined 6 GiB and require a
20 GiB free reserve. Real combined scratch/cloud hidden-copy accounting is a gate.

Historical restore only accepts current-generation verified data while a surviving
verified authority holds the source lock and completeness is established. It never
accepts a caller-supplied watermark or stale clean manifest. Missing authority/history
quarantines old copies; a NEW empty recovery store has no old facts and capture
disabled. Isolated eligible restore uses a new environment UUID/password/auth
generation, erases sessions, preserves trusted owner mapping and also keeps capture
disabled. There is no automatic capture re-enrollment or stale failover endpoint.

## Current local integration and verification evidence

The September 29 implementation review identified frontend/session, recovery binding,
assessment-context and parent-route gaps. This continuation resolves those **locally**.
The earlier build failures were dependency-file `ETIMEDOUT` reads, not evidence of a
successful build. Clean isolated builds below supersede that failed-build gate.

- **636 backend tests passed**, including **24 runtime tests**. The earlier pre-edit
  baseline was 612 tests; first runtime checkpoint was 634/22. Fresh synthetic data,
  local passwords and age identities are isolated; no canary or personal DB is used.
- **86 frontend tests passed**, including four new session tests and the existing
  exact retry/expiry, privacy invalidation, bounded paging and read-retention tests.
- **Both default and synthetic production builds passed**, including type validation
  and 14 generated pages, in `/private/tmp/sid157-integration-9a54e1d4/frontend`.
  Clean `npm ci --ignore-scripts --no-audit --no-fund` used the existing lockfile;
  package.json and package-lock.json are unchanged. Final Node **v22.22.2**, npm
  **10.9.7**, Next.js **15.5.19**. Initial clean success used Node v23.7.0;
  the final default/synthetic builds use Node 22. No dependency changes masked the
  filesystem failure. The original installed dependency directory was not repaired.
- Final **real Chromium/Playwright browser flow passed** on the synthetic production
  build: login → reviewed supported derivatives capture → authenticated receipt/status
  → reload/recovery → logout → rejected access. Explicit consent was required before
  the first capture; it was granted through the UI. No provider app was mounted.
- A browser-only aborted delivery retained its original command/key/text/timestamps;
  reload recovered it. Retry was absent until status lookup returned not found.
  Retry POST body was **byte-identical** to the original intercepted body, returned
  `applied`, and matched authenticated `found` status/receipt. Incompatible journal
  entries were removed. Final settled reload retained owner access and no pending
  command. Logout removed session/College journals; unauthenticated access and the
  captured revoked cookie both returned **401**.
- Browser privacy confirmation returned an applied forget receipt; diagnostics
  still showed **backup_sanitation=pending**. Browser explicit assessment rejected
  a client baseline with **400**, applied server-retained inputs, and returned the
  same receipt with `duplicate` on exact replay. This was an explicit API command,
  not an assessment produced automatically by Today or reload.
- Read-only `/runtime/session` verifies UUID/owner/workspace/auth generation without
  renewal. CSRF is tab-local; no provider credential is read or forwarded. In-memory
  response epochs and retained-query invalidation discard old session completions.
  Even failed storage removal immediately unmounts authenticated views. New tabs
  without the tab-local CSRF record must sign in. Closing/clearing a tab can lose
  unresolved delivery information; browser historical retention limits remain.
- Parent allowlist: authenticated **GET `/today`** builds the existing pure retained
  College brief. **GET `/activity` and `/morning-state`** return explicit **503
  provider_parent_disabled**. No parent writes/provider routes are enabled. Calendar
  emptiness is displayed as unavailable, not evidence of a clear schedule. Synthetic
  navigation mounts only Today/College; default developer-key behavior is preserved.
- Explicit assessment supports only the fixed cross-course owner scope. It uses
  retained canonical facts/coverage and at most 25 authorized context items, filtered
  to active nonsensitive `college-operational/1` items with usable required raw source.
  Calendar baseline/window are **unknown**, not fabricated. Client baseline/window,
  identity/context hints and unsupported scopes are rejected. Fingerprints and
  generation bind inputs once to the original command/key; no content copy is stored
  in `runtime_assessment_inputs`. Changed retry content or stale unfinished context
  is refused. Settled original receipts remain recoverable after privacy changes.
- The bootstrap-only pre-release synthetic schema now requires that fingerprint
  table. A prior candidate DB missing it fails closed; no silent in-place upgrade or
  personal migration is performed. Production migration/rollback remains an external
  review gate. The ARM64 explicit source list includes the new pure integration graph.
- Existing tests reverify process ownership, restart/crash receipt/outbox atomicity,
  scoped read/status, revocation races, raw expiry, quota/gap/lost-sync pending state,
  local age encryption/rotation and isolated restore/session reset/quarantine. HTTP
  boundary tests cover Host/Origin/CSRF/body/rate limits, provider denial and safe
  logs. Session and Today reads leave database bytes unchanged. These do not prove
  Oracle, OCI sanitation, physical erasure or independent Mac recovery.

Temporary local evidence: `/private/tmp/sid157-integration-9a54e1d4/` contains
`backend-tests.log`, `frontend-tests.log`, `build.log`, `build-default.log`,
`browser-final.log`, `browser-smoke.js`, isolated frontend/data and Playwright
snapshots. `/tmp/sid157-deps` holds test-only crypto packages. The earlier runtime
checkpoint logs remain under `/tmp/sid157-*`. These are local test artifacts, not
an export, release or backup destination. Only loopback test listeners were started;
they are stopped at the checkpoint. No tunnel or public listener was enabled.

## Unrun acceptance gates / review limitations

The [deployment matrix](../deployment/sid157/README.md#oracle-go-no-go--every-item-untested-here)
gives concrete go/no-go evidence for every external step. **Oracle account/free
capacity/charge manifest, native ARM64 install/build/resource fit, private phone
access with Mac asleep, real VM/mount/reboot, OCI conditional backup export,
independent Mac permissions/encryption/Keychain/offline recovery/pull/restore,
Tailscale private HTTPS/revocation and actual ChatGPT MCP/OAuth connectivity are
all untested.** No $0 resource has been provisioned; no uptime promise is proven.

The owner-session frontend, authenticated recovery binding, retained assessment
assembly and minimal parent allowlist are now locally verified. Private hosted
HTTPS/phone access and connected staging are still untested. No OAuth, MCP transport
or connected-write entitlement is claimed; ChatGPT-labeled capture remains denied.
This is an implementation-review checkpoint, **not completion of live acceptance
criteria**. No Calendar reconnect, general scheduler/notifications, broad UI/provider
extraction or downstream capability is authorized. Operational expiry/backup
maintenance and on-open reads do not establish proactive monitoring. Blinn remains
pending administrator approval. The approved conditional $0/no-PAYG architecture and
all directed dependencies remain intact.

Current live readback retains In Progress and the original eleven downstream
blocks, sole architecture blocker and no related links. Earlier detailed/minimal
comment attempts were rejected by automatic approval review and were not posted.
The owner subsequently approved only the following exact Linear note, which was
posted as comment `ad3bec2c-762d-44c6-bf8b-ddd23a3c83aa` at
`2026-09-30T13:25:17.533Z` and read back for exact equality:

> Local continuation reached the unstaged review checkpoint. Review and handoff updated; external acceptance remains unverified. Issue remains In Progress.

Publication preparation re-read this comment from the live issue. It does not
approve publication, deployment or issue completion; no new comment or issue
mutation was made during this preparation.

## Final-byte publication preparation reconciliation

No implementation or test source changed during this preparation. All 30
non-documentation candidate SHA-256 values match the prior saved final-byte
manifest. The 636-test backend log follows the final backend source/test bytes;
all 86 frontend tests correspond to the unchanged final frontend bytes. The
isolated clean frontend source still matches the checkout byte-for-byte, with the
unchanged package/lockfile; both existing successful default/synthetic builds
postdate those copied source bytes. They include Next.js type validation and all
14 pages, with Node v22.22.2, npm 10.9.7 and Next.js 15.5.19. These suites and builds
were not repeated merely for documentation changes.

Two evidence gaps were resolved: standalone `tsc --noEmit --incremental false`
passed against those identical clean bytes, and the real Chromium browser flow was
repeated against the final backend bytes. The prior browser record predated the
final malformed-request guard; the renewed flow verifies login, supported capture,
receipt/status, reload/recovery, incompatible-journal clearing, status-before-exact
retry, byte-identical POST, logout, revoked-cookie/unauthenticated 401 and retained
state clearing. An authenticated malformed array POST returns 400 while readiness
remains 200. No code was changed to pass these checks.

New temporary evidence files in the same isolated directory:
`typescript-publication.log` (empty output, confirmed exit 0),
`browser-publication.js`, `browser-publication.log` (structured passing result),
and `publication-reconciliation.json` (final per-path hashes and evidence binding).
These are internal local test artifacts, not an export or publication. Earlier
privacy/assessment/browser evidence remains applicable to identical source bytes.
The two documentation paths alone are reconciled for the approved posted note,
live remote baseline, precise publication scope and final-byte verification.

All ten frozen hashes, approved architecture proposal/addendum, original committed
handoff prefix, package/lockfile and empty index were rechecked. Candidate and
frozen paths account for the complete dirty inventory. `git diff --check`, explicit
candidate whitespace checks, review inventory/hash-table readback and final handoff
reconciliation pass. Loopback API/frontend and the isolated browser are stopped.
SID-157 remains In Progress and its criteria/dependencies are unchanged. This is
ready only for review of the local implementation publication candidate; release
and every unrun external acceptance gate remain separate.

## Stop boundary

All candidate work is unstaged. No external/OS account, payment details, resource
provisioning, public exposure, personal-data migration, deployment, commit, push,
Obsidian/other export, issue closure or downstream start occurred. Approved SID-156
proposal/addendum remain committed-byte-identical. The handoff has only the authorized unpublished continuation record. Review this candidate
before any separate release or synthetic infrastructure authorization.

Final reconciliation: HEAD and tracked origin/main still match the expected
`aa3939a2aed2b884e5871ac178c9abb3f6e6482a`; index is empty. All **10/10**
frozen SHA-256 values match the saved starting manifest. Proposal/addendum and
frontend package/lockfile still equal committed bytes. Handoff changes consist
only of the appended local continuation section. `git diff --check` passed.
The 32 candidate paths above plus the ten frozen paths account for the dirty
working tree; no unrelated paths were introduced. The publication reconciliation
manifest records final hashes and verification bindings with the isolated evidence.

## Frozen files — reverified against starting bytes

| Path | SHA-256 |
| --- | --- |
| `backend/.env.example` | `dc8d70775d56dca291b081c72bf6d148c5af886913fae002176cf0828e7359bc` |
| `backend/app/config.py` | `9554951cc8ff2dea312c29a9fe97f130aee0011fd77d1c0f11d5ccba735dac80` |
| `backend/app/email_analysis.py` | `cbbed4b3ec1a04654c47f8d21058f905cd19aca1bab2ffb2f2c39c6cf4a5925e` |
| `backend/app/email_duplicates.py` | `e1ed6cf1ee2f65998dc3dad5cfa443ce11fa866e21ea775d7e43fe0758e904ee` |
| `backend/app/gmail_client.py` | `17440a6ec9d73a3a258203bfd14ab0629e8bf190cb53a7492a29913e12f0a761` |
| `backend/app/main.py` | `275b1e150ca26c02b365975cb6652d7fa70a85d579b3b80588fd718c539be3d5` |
| `backend/app/microsoft_graph_mail.py` | `80f066ac83cd65910ca80ab7709f0ffb19407dc964731df27a568dfa5b4040a7` |
| `backend/scripts/blinn_email_oauth_setup.py` | `b0450b5dfbe1553d2578a63003b7f5e64972ef0597eedffc4e8dc2c3a42fb3f3` |
| `backend/scripts/verify_blinn_email_analysis.py` | `0f2642686a92c7e2edb25b7b2242d2f79862cc64fe2e6a0658a9c4616047a3bb` |
| `backend/tests/test_blinn_microsoft_graph_provider.py` | `5eb9bae9cf60521c3bf1c13b90513ce9bb50c0fd4116ee020b2bd4ec03f40e18` |
