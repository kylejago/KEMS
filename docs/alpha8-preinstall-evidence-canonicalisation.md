# Alpha8 pre-install evidence canonicalisation

This slice is an **ownership-only** Alpha8 refactor. It moves the proven Alpha7.20 pre-install historical evidence and dashboard installers behind a canonical, non-versioned facade without changing their runtime bodies or execution order.

## Canonical ownership

- `agile_preinstall_evidence.py` owns the two installer entry points.
- `agile_preinstall_evidence_runtime.py` is byte-identical to historical `agile_alpha720_preinstall.py` at blob `7242441149ef34bb7e0a31c0de4da3631dadc288`.
- `agile_preinstall_dashboard_runtime.py` is byte-identical to historical `agile_alpha720_dashboard.py` at blob `4abcd4d13f02add98ee4920b87ee3ff302214735`.
- Historical Alpha7.20 files remain packaged regression evidence.
- Historical `ALPHA7_COMPATIBILITY_ORDER` metadata remains unchanged.

The live registry still installs the pre-install evidence wrapper first and its dashboard wrapper second, after the canonical Alpha7.19 validation dashboard and before canonical Alpha7.22 price-horizon safety.

## Why no legacy-name bridge is required

Unlike the Alpha7.19 and Alpha7.22 migrations, no frozen downstream runtime imports either `agile_alpha720_preinstall` or `agile_alpha720_dashboard` by module name or mutates their module globals. Later behaviour consumes the shared backfill/dashboard objects after the Alpha7.20 installers have already patched them. The canonical facade therefore delegates directly to the byte-identical runtime modules and intentionally does not bind historical names through `sys.modules`.

## Preserved behaviour

The pre-install evidence path remains hypothetical and transparent: measured Home Assistant whole-house history may be combined with historical Open-Meteo tilted irradiance applied to the accepted proposal geometry. Reconstructed PV is explicitly not actual solar generation and historical reanalysis is not represented as the forecast KEMS would have had at the time.

Native KEMS and existing direct backfill evidence retain priority. Reconstruction stays daily-cached and fail-safe, and network evidence failure must not break KEMS. The existing `recorder.get_statistics` call remains read-only evidence collection.

The dashboard continues to distinguish digital-twin shadow readiness from hardware shadow readiness and continues to state that neither stage sends inverter writes.

## Safety boundary

This migration does not add a FoxESS provider write, inverter service call, or commissioning bypass. The evidence runtime continues to publish `real_hardware_writes: blocked`, and downstream canonical shadow/control layers continue to keep real commands disabled. **real hardware writes remain blocked**.

No tariff, discharge, export, reserve, SOC, house-first, price-horizon, simulation, commissioning, release, tag, or version behaviour changes in this slice.
