# HAPI MDM projection extension

This is a separately built HAPI 8.12.0 extension. The Python middleware image
does not include or deploy it. Its Dockerfile uses the exact HAPI image digest
currently running on `001-l-hlt01` and places the extension JAR in the
`/app/extra-classes` directory read by HAPI's `PropertiesLauncher`.

The extension contains a fail-closed read boundary, a capture migration and an
opt-in, bounded laboratory identifier projector:

- Patient resources leaving HAPI storage are checked through a HAPI read-only
  status transaction, joining an active transaction where present. Deferred
  conditional-create view callbacks can run after the original transaction;
  they also receive a transactional status check.
- Patient REST read/search/history/meta and system-history requests check before handling,
  so empty searches, `_summary=count` and `_count=0` cannot bypass the
  known-blocked status merely by returning no Patient resources.
- System, Patient and Group `$export` entry points and `$export-poll-status`
  check before handling. GET/POST polling is blocked while unpublished;
  DELETE is left to native cancellation handling. Blocked starts enqueue no
  `BULK_EXPORT` job. This does not guard old export-file/Binary URLs.
- Native batch/transaction write-entry subrequests inherit the enclosing
  BATCH/TRANSACTION operation. Their actual HTTP write method identifies source
  write preparation; embedded GETs retain their own read operation and guard.
  Conditional creates returning an existing Golden or redirected Golden
  still require readiness, including deferred representation callbacks.
  Existing-source conditional creates remain available.
- MDM link, duplicate, and history reads through `IMdmControllerSvc` run in a
  HAPI read-only transaction and use the same status gate. The internal query
  service is not wrapped to avoid intercepting internal MDM processing.
- Both HAPI MDM bulk-export expanders check readiness before `expandGroup` or
  `expandPatient`. This guards those expansion entry points, not the entire
  asynchronous export pipeline or downloads of previously generated files.
- In isolated HAPI, two Patients with the same synthetic EID were accepted
  under `BLOCKED_TEST` and produced two `mpi_link` rows. This covers one basic
  asynchronous MDM path, not retries or every MDM operation.

Both migrations provide `omni_patient_projection_read_status()`. Neither
reports `READY`. No migration runs automatically when the JAR is loaded.
The early REST check is deliberately only a fail-closed precheck, not a
coherent publication/read snapshot. It must not be used to justify returning
`READY` in a future migration without a complete reader protocol.

For the development handover and the next work block, see
[2026-11-26 handover](../docs/project-memory.md#tagesabschluss-2026-11-26-mdm-arbeitsstand-und-wiedereinstieg).
This is a saved development state, not a deployment approval.

## Capture migration

V001 must be applied during maintenance, with HAPI and all other writers
stopped. Use the HAPI database/schema, PostgreSQL 16, READ COMMITTED, a verified
backup, and `psql -X -v ON_ERROR_STOP=1 -f .../V001__patient_projection_outbox.sql`.
The script owns its transaction. Set the intended `search_path` before invoking
it; it does not assume that HAPI uses `public`. Do not reapply or edit a migration
after deployment. An error rolls back installation; it is not an implicit reset
or an online-upgrade/retry mechanism.

- Installation locks the seven HAPI input tables until capture, queue, and one
  full-inventory `BOOTSTRAP` job are committed together. Existing Patients,
  including deleted records, need not be empty. Bootstrap is **queued work**,
  not an already completed backfill.
- Patient resource/history/tag/provenance writes and MDM link changes enqueue
  work in the writer's database transaction. Shared tag definition changes
  invalidate referenced Patients. Events retain old/new internal metadata and
  affected PIDs, not FHIR payloads or identifier values.
- Unresolvable endpoints and newly unsupported partitions/encodings enqueue
  unresolved work and block claims. They are never treated as harmless changes.
  Existing unsupported Patient partitions/encodings and partitioned MDM links
  are rejected at installation.
- Input table shape, primary keys, capture/enqueue triggers, and journal
  protection are checked. Triggers are `ENABLE ALWAYS`; input `TRUNCATE` and
  journal rewriting are rejected. This is not protection against the database
  owner replacing functions or DDL. Keep schema/trigger administration outside
  normal application operation; HAPI upgrades require explicit revalidation.
- `omni_projection_claim(worker_uuid, lease_ms)` claims work with `SKIP LOCKED`,
  an owner, a lease of 100..300000 ms, and a monotonically increasing fence.
  `omni_projection_fail(event_id, worker_uuid, fence, failure_code, delay_ms)`
  schedules a retry or exhausts the five-attempt budget. Failure codes must be
  fixed uppercase codes, never patient data or exception messages.
- In V001 there is deliberately **no acknowledgement API, success job state, worker
  scheduler, or READY switch**. Starting a claiming loop now would only consume
  retry budgets. Leased jobs survive restart; expired leases can be reclaimed,
  but exhausted/unresolved work remains blocked for operator review.

Capture is not a coherent projector snapshot or a commit barrier. Event IDs are
not commit order or a safe numeric acknowledgement watermark. A subsequent
migration must couple fresh Source/link recomputation, versioned HAPI DAO
updates, exact work acknowledgement, and the reader boundary. V002 implements
the projector and acknowledgement, **not** reader publication. Do not copy
identifiers by direct SQL updates to HAPI payloads. Outbox retention/cleanup is
also deferred until that protocol exists.

## Laboratory projector (V002)

Apply `src/main/resources/db/migration/V002__patient_identifier_projector.sql`
only after V001, during maintenance with all writers stopped and a verified
backup. Use the same schema and `psql -X -v ON_ERROR_STOP=1 -f ...` procedure;
V002 owns its transaction and refuses implicit reinstallation/reset.
Enable the Java bean explicitly with `omnilink.mdm.projection.enabled=true`.
It is disabled by default. Automatic dispatch has a separate opt-in described
below; there is no production HTTP control endpoint.

- `PatientIdentifierProjector.claim` and `apply` require separate root HAPI
  transactions. The projector validates the resource-local JPA transaction and
  writable READ COMMITTED JDBC connection.
- Each job performs a full recomputation, bounded to 1000 Patient rows
  (including tombstones) and one complete MATCH page of at most 1000 links.
  Exceeding either bound or finding ambiguous/unsupported input aborts the
  transaction. These limits are implementation bounds, not scale acceptance.
- Before reading inputs, the projector takes `SHARE ROW EXCLUSIVE` on all
  seven captured tables, in a separate SQL statement. This blocks writers and
  other projectors until commit/rollback. Lock timeout is two seconds;
  statement timeout is fifteen seconds per statement, not an overall job SLA.
  This deliberately coarse laboratory strategy is not an availability or
  performance approval for a shared HAPI server.
- Confirmed live sources contribute deterministic system/value identifiers
  with managed markers and sorted source-reference provenance. Changed or
  removed managed identifiers are reconciled; identifiers unowned by the
  projector and present in its locked Golden snapshot are retained.
- Golden updates use the HAPI DAO with version-qualified IDs. The exact claimed
  event's immutable receipt and acknowledged job state commit in the same
  transaction. Event-ID watermarks are not used. Golden self-events remain
  pending and converge through subsequent no-op jobs.
- A persisted receipt permits historical replay of the same owner/fence after
  a lost response. Replay is not a statement that current data is published.
  Do not blindly call the failure API after an ambiguous commit response.
- Fully drained work still reports `BLOCKED_READER_NOT_PUBLISHED`. Pending,
  exhausted, unresolved, or invalid capture/receipt contracts remain blocked.

**Manual identifier policy:** HAPI's native NO_MATCH handling rebuilds the
Golden from survivorship rules. With projection enabled, a separate
write-only interceptor is registered on HAPI's global storage interceptor
service, so it also covers internal MDM writes. The read guard remains
request-scoped; registering it globally would interfere with internal MDM.

Explicitly manual identifiers carry
`urn:omnilink:mdm:identifier-projection:manual=true`. An authorized, trusted
Java workflow must use `SystemRequestDetails` with the server-side user-data
key `GoldenManualIdentifierPolicy.MANUAL_EDIT_CONTEXT` set to `Boolean.TRUE`.
This is not an HTTP header or a public endpoint. New keys added in that context
are marked manual; existing unclassified keys are not silently adopted.
Existing keys can be explicitly classified using the manual extension in
that same trusted context. Manual edits/replacements/deletions are respected.
Ordinary internal writes restore previously marked identifiers including
their metadata, but never turn projected source identifiers into manual ones.
When a rebuild retains a previously managed key but drops its extensions,
its known managed ownership is retained until fresh projection recomputes
the current source set. Missing source keys are not restored. This does not
adopt previously unclassified identifiers. Combining manual and source
ownership, duplicate/conflicting ownership, and missing old Golden snapshots
are rejected, including attempts to strip managed markers and reclassify
the same key through the manual-edit context.

HAPI's public write restriction for MDM-managed Goldens remains in force
(`403`); this module does not add a production manual-editor/API or weaken
authorization. The test-only fixture exercises the trusted Java workflow.
Before rollout, existing native identifiers require explicit classification,
not blanket adoption. Unclassified native values can still be removed by
HAPI. Deleting the last source may remove the orphan Golden; the policy does
not resurrect deleted resources. History-rewrite, parallel merges and further
failure/restart/restore acceptance remain outstanding.

**Golden merges:** With projection enabled, a primary decorator delegates to
the pinned native `mdmGoldenResourceMergerSvc`. Patient merges require
versioned active Golden snapshots, checked against stored resources; other
resource types retain their native path. Only an internal synchronous merge
scope authorizes the transfer of already-manual identifiers to the surviving
Golden. The scope matches stored Patient IDs/versions and is always cleared
on exit, including failure; it is not an HTTP header or a manual-edit bypass.
The native intermediate Golden-tag removal is permitted only when it changes
no other Patient content. The redirected former Golden can retain its
historical manual identifiers; this does not authorize manual markers on
ordinary sources.

Equal managed keys combine validated source provenance during native merge.
Conflicting manual ownership, manual/native collisions, or differing metadata
for an equal key are rejected before delegated merge writes instead of
silently choosing a value. Successful normal and manually supplied merge
payloads, reassigned MATCH links, shared-key provenance, manual preservation,
and subsequent actual NO_MATCH rebuilds are tested.

The pinned native `MdmLinkDaoSvc.deleteLink` uses `REQUIRES_NEW`, allowing
duplicate-link deletion to survive a later failed merge. This was reproduced
with actual native merges. With projection enabled, a primary JPA link-service
adapter keeps deletion in the existing transaction **only** inside the
protected Patient merge scope; it requires an active transaction and reuses
the native validation/delete implementation. Outside this scope it delegates
to the original service, preserving native transaction behavior.

Injected failures after native merge execution and during deferred commit
now roll back both Golden snapshots/tags, all links (including pre-existing
duplicates) and capture events together. A fresh retry succeeds. A simulated
lost post-commit response retains the committed redirect; repeating that
merge is rejected without changing versions or links. These selected probes
are not parallel-merge, application-kill-during-merge, database-crash or
restore acceptance. Do not retry an uncertain merge blindly.

Concurrent HAPI link updates can also fail optimistic locking after waiting
for projection; the isolated test verifies rollback and a fresh retry, not
automatic production retries or atomicity of every MDM operation.

Still outstanding: full reader/paging/cache/bulk coverage and publication
boundary, parallel-merge and history-rewrite acceptance,
inventory/scale checks, controlled manual-edit
and exhausted/unresolved-job recovery operations, database crash/restore and
rollout/rollback acceptance. Do not deploy this as an available
identifier-projection service yet.

## Automatic laboratory worker

After both migrations, enable automatic dispatch explicitly with both:

```properties
omnilink.mdm.projection.enabled=true
omnilink.mdm.projection.worker.enabled=true
```

The worker flag defaults to false. Enabling it without the projector prevents
startup; enabling it before V002 cannot consume capture-only job budgets.
These settings are not applied to the running laboratory configuration here.

- Spring schedules one serial tick per second after the preceding tick
  finishes. Each tick claims at most one eligible job with a 30-second database
  lease and performs a fresh full projection. Multiple HAPI instances still
  serialize input snapshots through the existing database locks.
- A failed/uncertain apply is **not** blindly failed or reapplied. A separate
  root transaction locks the same job, waiting for any earlier job holder to
  commit or roll back. A subsequent statement checks its immutable receipt.
  An acknowledged matching owner/fence is reported as historical completion,
  without rewriting the Golden or scheduling a failure.
- Only a still-owned, live, unacknowledged lease without a receipt can enter
  the existing failure API, with fixed code `APPLY_FAILED` and a five-second
  retry delay. Claims retain the existing five-claim budget and increasing
  fences. Uncertain claim/recovery responses leave durable state in charge;
  abandoned leases are reclaimable after expiry, not overwritten.
- Observed unresolved capture or exhausted work pauses dispatch for operator
  review instead of consuming other job budgets. There is deliberately no
  automatic exhaustion reset, journal deletion, or unresolved-event override.
- Worker logs contain only fixed phases, event/fence/count metadata and
  exception class names, not exception messages or FHIR payloads/identifiers.
  `PatientProjectionWorker.state()` exposes an in-process heartbeat, phase and
  completion-observation time for Java monitoring. It is not a readiness API;
  `IDLE` means no eligible job was found, not that no leases/pending jobs exist.
  A historical receipt observation does not establish current projection
  freshness.
- Reader publication remains disabled even after automatic drain. Full scans,
  coarse table locks, one job per tick and the fixed lease are laboratory
  bounds, not throughput, availability or total-job-duration approval.

For operator diagnostics, use the migration schema and metadata-only queries:

```sql
SELECT omni_patient_projection_read_status();
SELECT state, count(*), max(attempts) FROM omni_projection_job GROUP BY state;
SELECT event_id, state, attempts, fence, failure_code, available_at, lease_until
FROM omni_projection_job WHERE state <> 'acknowledged' ORDER BY event_id LIMIT 20;
```

Stopping or losing HAPI can interrupt work; committed receipts remain
authoritative and unacknowledged leases survive. Do not manually mark work
acknowledged or clear exhaustion merely to obtain an available read status.

## Isolated integration tests

Run from this module with Docker available:

```sh
bash src/test/run-outbox-integration.sh
```

The script builds the current JAR, boots the pinned HAPI image and PostgreSQL 16
in a private internal Docker network without host ports, and creates only
synthetic data. It installs V001 against nonempty HAPI storage, verifies
job/lease persistence across an **orderly** PostgreSQL restart, then enables
the current JAR's guard and runs V001 integration and reconciler tests. It
stops HAPI, applies V002, restarts HAPI and runs actual projector integration
tests with automatic dispatch disabled. It then enables the worker only in
the private fixture, kills that HAPI container while completion is blocked,
verifies its persistent lease without acknowledgement, and restarts it.
Automatic reclaim/projection and bounded retry exhaustion are then tested.
The PostgreSQL
tests use disposable schemas cloned from the actual HAPI-created input tables;
the HTTP tests use actual HAPI writes and asynchronous MDM link creation.
Bulk export is enabled only in the isolated fixture to exercise its real
REST entry points, not merely absent-operation responses.
The tests require the database name `mdm_outbox_test` and fixed synthetic
credentials. Never point them at the running lab database.

Test controls are compiled only into the separate `*-tests.jar`, loaded only
by this harness, gated by `omnilink.mdm.projector-test-fixture=true`, and refuse
startup outside `mdm_outbox_test`. Never copy the tests JAR or enable the
fixture package/settings in a deployment. The normal Dockerfile copies only
the main extension JAR.

The script removes its containers, network and build/JAR volumes on exit.
Only the reusable Maven dependency cache `omni-hapi-mdm-test-m2` remains.
Maven dependency downloads use a separate build container with network access;
the HAPI/database tests have no external network access.

The latest complete run passed 72 tests without failures or skips: 27 V001
integration tests, 23 reconciler/manual-policy/worker unit tests, 21 V002
projector/recovery/merge tests and one automatic-worker integration scenario.

For an already prepared isolated fixture, the underlying Maven command is
`mvn -Dtest=GoldenIdentifierReconcilerTest,GoldenManualIdentifierPolicyTest,PatientProjectionWorkerTest,OutboxMigrationIT,OutboxHapiIT test`
before V002 and `mvn -Dtest=PatientIdentifierProjectorIT test` after V002, with
`MDM_OUTBOX_TEST_URL` and `MDM_OUTBOX_TEST_FHIR_BASE` set. These `*IT` tests are
explicit opt-in; a normal Maven build does not prove database/HTTP integration.
`PatientProjectionWorkerIT` additionally requires the harness's interrupted
worker setup and `MDM_WORKER_RESTART_EVENT_ID`; do not run it in parallel with
manual projector tests or against a shared fixture.
The tests cover actual identifier changes, native preservation within the
projector, preservation of explicitly manual identifiers across actual HAPI
NO_MATCH rebuilds, explicit manual deletion, unchanged public Golden-write
blocking, source/deletion handling, atomic rollback after DAO flush and
at deferred commit, lost-response replay, fence/lease rejection, source/link
writer contention, bounded projector lock failure, receipt protection, no-op
convergence, receipt-aware recovery across an in-flight commit, lost recovery
responses, automatic crash recovery and retry-budget blocking, and continued
reader blocking after drain. Merge tests cover normal/manual payloads,
confirmed-link reassignment, manual transfer, shared source provenance before
and after unlink, rollback after native execution/deferred commit with and
without duplicate-link deletion, fresh retry and a lost merge response.
Reader probes cover empty/count Patient and system-history responses, export
kickoff/polling with no enqueued job, source-only write bundles, mixed
write/count bundles, and direct/bundled conditional Golden reads. HAPI returns
embedded GET failures as per-entry `503` OperationOutcomes inside an HTTP `200`
batch/transaction response; the tests require those entries to contain no
resource/count. This preserves native behavior: preceding writes can commit.
An outer HTTP `200` is not proof that each embedded read succeeded.
A hard-killed application worker is not a database-crash/full-restore,
parallel-merge, history-rewrite, scale, paging, or bulk-export acceptance.

After isolated validation, HAPI configuration must set:

```yaml
hapi:
  fhir:
    custom-bean-packages: ch.omnilink.fhir.mdm.extension
    custom-interceptor-classes: ch.omnilink.fhir.mdm.extension.PatientProjectionReadInterceptor
```

These settings are not added to the production Compose configuration here.
