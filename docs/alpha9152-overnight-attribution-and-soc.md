# KEMS Alpha9.152 — safe overnight performance attribution and SOC presentation

## Problem / evidence (28 October 2026)

Home Assistant is stable and there are no watchdog-forced Core restarts since 22 October. However, selected KEMS coordinator refreshes between 03:15 and 05:00 took 22–29 seconds, correlated with Ohme, Hive, Ring and Supervisor API timeouts. A 04:59 KEMS scan took 21.421 seconds, with 10.48 seconds attributed to the aggregate *control_and_physical_safety_planning* stage. The 07:47 diagnostic later showed 60-scan mean 3.174 seconds, 88 historical Agile days compared, historical manager comparison 1.219 seconds, no physical balance errors and 91% physical SOC.

**Correlation is not proof** that KEMS stalls the Home Assistant event loop. An awaited executor call can be delayed by executor saturation without blocking the loop. Pre-existing aggregate timings mixed synchronous planning, coroutine waits and third-party I/O.

## Read-only instrumentation

- Historical 88-day Agile comparison remains a *single awaited executor batch*, preserving complete SHA-256 fingerprints, late rate/backfill invalidation, chronological SOC chain and live/tomorrow evaluation. Report `historical_batch_worker_seconds` (actual worker elapsed), `historical_batch_await_seconds` (total caller wall time), and `historical_batch_wait_overhead_seconds` (difference including queueing/result transfer). **Do not equate this difference with event-loop blocking.**
- New internal coordinator substage timings: `forecast_refresh`, `history_record`, `control_plan_and_event_overlays`, `physical_export_reserve_guard`, `ev_hold_and_export_commissioning`, and existing `shadow_recorder`. The `agile_rolling_price_optimisation` stage continues to publish the manager's internal comparison metrics.
- `coordinator_performance.slow_hourly` retains one worst-case outlier per UTC hour and the count of scans over 10 seconds, keeping 03:15–05:00 evidence visible after later morning refreshes replace `recent_slow_scans`. Logging remains throttled to one warning every 10 minutes; warnings include the slowest substage and Agile worker-versus-overhead measurement. The extra evidence is kept in memory and does not write to Recorder.

## Forecast and dashboard presentation

The prior projected overnight maximum was **85.7%** from an assumed **15%** starting SOC. Actual FoxESS SOC reached **91%**. These are not contradictory: the assumed starting SOC is not a measured starting level. The Home tab now shows measured physical SOC, advisory simulated SOC, percentage-point difference, morning requirement, and a **hypothetical next cheap-window ceiling**. The Tomorrow tab no longer labels that value as an overnight *charge target*. This is a presentation correction only.

**Simulated SOC intentionally differs from physical SOC**, as a counterfactual operating-policy model. A model mismatch must not be repaired by seeding the physical controller from simulation, or by forcing simulation to the physical meter. Live Data and physical reserve guards remain authoritative.

## Protections unchanged

- FoxESS command sequence and commissioning checks, independent physical-export guard, grid export ceiling 7kW, 15% soft reserve/10% absolute limit
- Confirmed Octopus Intelligent cheap-slot requirement before EV/battery charging; cached/unconfirmed dispatch data must not grant new permissions
- EV connected/idle export policy, Power Down and Happy Hour priorities and booked-event requirements
- Home Assistant scheduled KEMS update window 06:00–06:30, no forced background restart during export
- ESPHome firmware panel.4, KEMS Pi agent and websites remain at their published versions

## What this release does **not** claim

This release improves attribution, diagnostic retention and model presentation. It **does not claim** that the 03:15–05:00 slowdown's root cause has been removed. A subsequent morning diagnostic and Home Assistant Core logs can establish whether slow wall time is worker CPU, executor waiting, or specific awaited I/O; only then should we alter the critical calculation path. Avoid slowing or bypassing physical checks or throttling live Agile dispatch as a blind performance workaround.
