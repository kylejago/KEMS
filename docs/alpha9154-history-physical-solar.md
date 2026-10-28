# KEMS Alpha9.154 — history checkpoint isolation and physical solar-flow evidence

## 28 October 2026 runtime evidence

Alpha9.153 was live with 88/88 historical comparison days restored from its exact-input SHA-256 cache, 3,872 cache hits and no misses. At the 14:11 diagnostic the 5.844-second coordinator scan spent 3.137 seconds awaiting `HistoryRecorder.async_record`. Earlier checkpoints at 13:40 and 13:55 took 2.459 and 3.111 seconds. Existing `HistoryRecorder` called `Store.async_save` on every third sampled snapshot, re-serialising approximately 21,423 retained records on the time-sensitive control scan. This is a plausible direct explanation for the roughly 15-minute repeated delays. It does not explain the separate first-scan 10.766-second Agile-stage delay or prove an underlying HA event-loop block.

The same diagnostic showed 3.224 kW PV, 0.931 kW house load, 2.298 kW physically measured battery charging (negative battery power) and zero physically measured grid export, while the *advisory* digital twin projected 2.293 kW PV export. There is no independent metered solar-to-grid split.

## Changes

- Keep the original 5-minute observation interval and a durable save after three new records; keep `Store` version 1 and the same serialized `{"records": [...]}` schema.
- Schedule at most one Home Assistant-owned background checkpoint task per recorder. Build a detached list of retained snapshots and encode to dictionaries in the Home Assistant executor before the Store write. An ordinary `async_record` no longer awaits disk I/O.
- Track write revision and data still unsaved. Coalesce writes occurring during a pending checkpoint. On clean KEMS unload, await the in-flight checkpoint, retry a failed background write and flush all remaining observations, even fewer than three. Do not acknowledge any revision until Store confirms the save.
- Expose `history_persistence` in KEMS diagnostics: sample and pending count, in-flight status, attempts/failures, the last *worker serialisation* time, Store-await duration, total checkpoint duration, error and shutdown recovery status.
- Enrich the existing read-only solar-routing shadow with physical flow observations. Only show an explicitly **bounded inference** of PV-to-battery when telemetry ages are known and recent, EV is unplugged, grid import is negligible, and contemporaneous PV/house/battery/grid balance agrees. Otherwise report only directly metered flows; never claim an independent solar-to-grid meter. Surface this on the dashboard Home live flow.
- No change to historical replay cache/fingerprint, data acquisition cadence, optimizer dispatch, EV policy, 7-kW DNO export limit, 15% reserve target/10% absolute safety cutoff, commissioning and balance thresholds, Power Down, Happy Hour, updater maintenance window, panel/web/Pi software or FoxESS hardware writes.

## Validation

- Simulate slow Store writes: verify the next record and control tick proceed without awaiting storage.
- Serialize in a worker and preserve all records with ordered, coalesced saves including a final one-record tail at clean unload.
- Verify a failing store does not acknowledge the revision and can be retried on shutdown.
- Verify retention/pruning and the existing stored format.
- Validate physical PV charging inference against the 14:11 sample, stale/absent data, non-negligible grid import, EV connection and inconsistent power balance.
- Run all Python tests, Black, Ruff, source compilation, HACS, Hassfest and managed ESPHome panel compile. Deployment is independent of release publication; retain 06:00–06:30 installation and never install during export.

**Remaining issue:** the Alpha9.153 initial 10.766-second slow scan was dominated by other Agile-stage work (historical worker around 1.237 seconds). Do not claim this history checkpoint fix solves that first scan or the 03:15–05:00 HA stability issue until independently measured.
