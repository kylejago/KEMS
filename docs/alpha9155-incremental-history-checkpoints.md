# KEMS Alpha9.155 — incremental history checkpoint performance

## Live evidence driving the change

Alpha9.154 (28 October 2026, 18:55 GMT) retained approximately 21,477 five-minute observations. Background checkpoint persistence was reliable (15 successful, zero failures), but each executor checkpoint re-encoded the entire retained history and required approximately 18.3 seconds for encoding, with 0.97 seconds in the Home Assistant Store write. The coordinator history-record stage itself was 0.000 seconds. Concurrent heavy historical replay/fingerprint work correlated with 18–21-second scans, but a causal overlap is not yet proven.

## Bounded improvement

HistoryRecorder now keeps a JSON-ready representation beside each chronological observation. Stored history is already JSON-ready on load; each newly sampled observation is encoded exactly once, in the existing Home Assistant executor checkpoint worker, and reused in subsequent checkpoints. History pruning discards matching decoded and encoded observations together. A checkpoint only captures the revision it actually submitted; observations appended during a worker/write remain pending for the coalesced successor. A failed checkpoint is not acknowledged, and clean unload awaits any in-flight write and saves remaining observations.

The persisted Store remains schema version **1** with the same `{"records":[...]}` representation, observation interval remains five minutes, checkpoints remain every three new observations, and no new timer or parallel worker is introduced. Historical records are treated as immutable observations after capture; do not mutate them in place.

## Diagnostics and verification

`history_persistence` includes last checkpoint start/finish UTC times, reused vs newly encoded record counts, in-memory encoded-record count, executor encode seconds, Store await seconds, pending records, failure counts and in-flight state. Correlate these timestamps with `coordinator_performance` and Agile's historical replay timings in subsequent live diagnostics.

Regression tests exercise multiple checkpoints, JSON round-trip restart, exactly one new encoding after restoring six records, retention pruning alignment, failed-write recovery, delayed writes, and shutdown flush.

## Deliberately unchanged

The 88-day settled historical replay cache still validates **full exact-input SHA-256 on every restored or reused historical day**; no shortcut based on mutable input identities, provisional prices or timestamps is allowed. The fingerprint cost remains a separate measured optimisation candidate. Current-day and tomorrow planning, physical conservative SOC accounting, 15% target and 10% absolute cutoff, the 7 kW DNO export limit, 90% commissioning evidence, EV charging/Ohme guard, FoxESS commands, Power Down, Happy Hour, panel and safe-first installer rules are unchanged.

This change does not install itself into Home Assistant, restart Core or override the 06:00–06:30 no-export maintenance window.
