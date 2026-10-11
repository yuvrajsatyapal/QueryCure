# ADR-0015: Frozen canonicalization profiles, atomic run finalization, and an explicit integrity scope

- Status: Accepted (2026-10-11); amends [ADR-0010](ADR-0010-content-addressed-artifacts.md)
- Area: Replay / Data / Security

## Context
ADR-0010 introduced content-addressed artifacts but left four gaps:
- canonicalization was underspecified ("floats via repr", "keys sorted"), so digests could change across Python or library versions;
- the event digest, report, and manifest had no defined ordering, which invited circular hashing and partially written manifests;
- the docs called reports "tamper-evident", which overstates what same-database digests can prove;
- replay comparisons had no statistical definition.

## Alternatives
1. **Canonicalization.**
   - (a) Python `json.dumps(sort_keys=True)`: output depends on Python/Pydantic formatting details.
   - (b) **RFC 8785 (JCS) plus input restrictions, in a self-owned module with golden vectors.**
   - (c) CBOR/deterministic binary encoding: unreadable artifacts, new dependency.
2. **Digest.**
   - (a) Plain SHA-256 of bytes: identical bytes under different profiles collide in the unique key.
   - (b) **Profile-tagged SHA-256** (`profile ‖ LF ‖ bytes`): domain separation, still reproducible with `shasum`.
3. **Finalization.**
   - (a) Write report and manifest in separate steps: crash windows leave half-sealed runs.
   - (b) **One transaction with a fixed event cutoff and a one-directional hash chain** (events → digest → report → manifest).
4. **Integrity.**
   - (a) Sign manifests now: needs key management outside the DB.
   - (b) **Digests + append-only DB grants + manifest digest in exports, with an explicit statement that this is not authenticity.** Signing deferred.
5. **Replay comparison.**
   - (a) "CIs overlap": weak and asymmetric.
   - (b) **Bootstrap CI of the speedup-drift ratio with an equivalence margin**, classified per pair, worst-case aggregate.

## Decision
1(b), 2(b), 3(b), 4(b), 5(b), as specified in [REPLAY_ENGINE.md](../../architecture/REPLAY_ENGINE.md) §2, §5, §6, §9.

In addition:
- raw measurements are integers (ns, bytes);
- report building and Markdown rendering are separately versioned pure functions, and stored artifacts remain the record when an old version is unavailable;
- every replay request is a `replay_attempts` row with structured status and failure codes.

## Rationale & trade-offs
- + Digests are stable across Python, Pydantic, and psycopg upgrades; changing a rule forces a new profile ID.
- + No crash window can produce a manifest without a report or a report without a sealed event log.
- + Honest claims: replay proves consistency against stored digests, and exports give users their own anchor.
- − We own about 150 lines of canonicalization code and must keep old profiles forever.
- − Integer-only samples and fixed field presence make schemas slightly more rigid.
- − Without signing, a compromised metadata store can forge "verified" replays (documented residual risk).

## Consequences
Schema additions:
- `investigation_runs.finalized_at` and `events_cutoff_seq`;
- version columns on `investigation_reports`;
- `replay_manifests` gains the events cutoff and digest;
- `benchmark_runs.latencies_ns` replaces `latencies_ms`;
- `experiments` gains `environment`, `engine_version`, and `row_profile`;
- new table `replay_attempts`;
- `qc_app` / `qc_retention` DB roles.

API: replay endpoints return `ReplayAttempt`; new error codes `NOT_FINALIZED` and `EXPERIMENT_NOT_REPLAYABLE`; new SSE events `replay.status_changed` and `replay.compared`.

Changing the equivalence margin default or any profile requires updating REPLAY_ENGINE and the golden vectors.

## Amendment (2026-10-11): profile IDs renamed before first release

The project was renamed from QueryDoctor to QueryCure. The profile IDs became `qc-json-v1` / `qc-text-v1` / `qc-raw-v1` (and the planned `qc-row-v1`). This is the one permitted exception to "frozen": no release existed and no artifacts existed outside disposable local development databases. Canonical bytes are unchanged. Only the profile tag in the digest preimage changed, so the golden-vector digests were recomputed with plain `hashlib` (the method reproduced all 14 previous digests from the old IDs first). From here on the `qc-*` IDs are frozen without exception.
