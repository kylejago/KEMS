# KEMS Alpha9.153 — bounded restart-safe historical Agile replay cache

## Evidence from 28 October 2026

Alpha9.152 captured a 36.859 s coordinator scan at 11:12, with 35.474 s in the read-only Agile comparison stage. Of that, historical replay worker elapsed was 25.581 s and await elapsed 25.583 s (only 0.002 s overhead). At 11:18 the comparable worker time was 1.164 s. Diagnostics recorded 88 historical misses and 528 subsequent hits. This is strong evidence of **cold historical replay after a KEMS reload**, but not proof of Home Assistant event-loop blocking or the separate overnight 03:15–05:00 timeouts.

## Change

- Persist the existing maximum-400-day `HistoricalReplayCache` as release-scoped JSON in the existing Agile Smart Export Home Assistant Store. Store **only** settled historical comparison results and their full binary-pickle SHA-256 fingerprints. Never persist pickle objects or bypass a digest comparison.
- Restore cache entries on KEMS load. Every hit recalculates the **complete exact input** SHA-256 fingerprint, including source snapshots, complete simulation config, tariff, independently carried Agile/Full-KEMS SOC and actual per-day published rates/product. Changed inputs, backfill, late tariffs, code-release version, malformed storage and cache limits fail closed to normal replay.
- Update the store only when historical results genuinely change; use existing clean shutdown flush, and acknowledge the cache checkpoint only after successful Store save.
- Retain historical replay's single awaited executor batch, chronological SOC chaining, present-day calculation, tomorrow projection, published prices, and every physical-control guard. Do **not** defer the live planner, alter FoxESS commands, or weaken safety.
- Diagnostic `agile_historical_replay_cache.restored_days` and `pending_persist` identify successful warm starts and pending checkpoints. Existing worker, await and stage timings remain intact.

## Expected observation and limits

The first Alpha9.153 installation **will not have persisted Alpha9.153 replay entries yet**, so a complete 88-day warm-up may still be required. After a successful store checkpoint, subsequent integration reloads on the same release should restore settled results and avoid expensive replay, as long as all inputs match. Compare `restored_days`, `hits`, `misses`, historical worker seconds and scan wall time after a second startup; do not promise a fixed speedup without a measured trace.

This is a targeted cold-start mitigation. Daily upstream data corrections may rightly invalidate several days. The overnight 03:15–05:00 timeouts remain a separate investigation until post-install diagnostics establish causation.

## Protections and release

No changes to rolling physical dispatch, EV/Ohme status policy, confirmed Intelligent slots, independent 7 kW DNO export limit, 15% soft/10% absolute SOC limits, Power Down, Happy Hour, commissioning, control writer, or panel. Retain normal 06:00–06:30 local install window and do not install during export. This PR creates no Home Assistant restart or installation.
