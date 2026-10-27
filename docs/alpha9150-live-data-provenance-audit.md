# KEMS Alpha9.150 — live-data provenance and stability audit

**Date:** 27 October 2026 (GMT). **Code baseline:** Alpha9.149, main `11e76e7b3ec55cc906f678886ba9999bcc5955ea`. **Live diagnostic sampled:** Alpha9.148, 20:15:47 GMT.

## Live-data source matrix

| Operator field | Physical/authoritative source | Non-authoritative source or caveat | Finding |
| --- | --- | --- | --- |
| Live house/grid/PV/battery/EV power | `Collector` → validated `Snapshot` → `sensor.py` | Uncommissioned Octopus fallback is explicitly simulation-only and does not grant physical control | Correctly physical with freshness evidence |
| Current physical battery SOC | FoxESS `Snapshot.battery_soc` | A SOC sensor which only updates on change can have an old report time | Device report, not a continuously interpolated live SOC |
| Safe current battery-energy SOC | Bounded `PaidAgilePhysicalEnergyTracker` → same-scan `physical_planning_soc` → physical reserve guard | Does not credit speculative solar or simulated SOC | Conservative lower bound, distinct from FoxESS-reported SOC |
| Live paid Agile export request | Final `KEMSData.control.desired_battery_export_power_kw`, after `guard_paid_agile_physical_export`, EV hold, commissioning override | `SimulationState.target_battery_export_power_kw` was shown on Home as if physically authoritative | **Alpha9.150 change:** Home now uses final control snapshot |
| Physically allowed exportable energy | Verified rolling plan `physical_ac_export_budget_kwh` with applied cap and physical proof | Aggregate `forecast_path_scheduler.planned_battery_export_kwh` can exceed the final guard ceiling; generic simulation `exportable_battery_energy_kwh` is not a proof | **Alpha9.150 change:** show only physically verified AC budget |
| Today's observed site energy | FoxESS same-device cumulative daily counters where available; otherwise integrated physical power, via Alpha9.48 adapter | Accumulation gaps and partial days still require provenance and should not be equated with supplier meter settlement | Appropriate measured authority; clearly distinguish estimate/settlement |
| Today's electricity/export money | Actual observed/export power integrated across half-hour prices using `export_accounting.py` and whole-home tariff ledger | **Not settled Octopus payments**, baseline credits incomplete during some events | **Alpha9.150 change:** estimated credit and bill-equivalent labels |
| Agile price, decisions, future SOC | Published half-hour rates, safe live routing and separate replay forecast | `periods.*`, independent digital-twin `simulated_soc_percent`, scenario compare and historical replays are advisory | Do not mix historical and future replay SOC into physical readings |
| Power Down outcome | `last_power_down.physical_grid_export_kwh`, coverage, successful completion | Reward estimates may still use modelled plan rather than supplier settlement | Physical outcome separate from forecast bonus |

## Sample evidence and correctness

At 20:15 GMT on 27 October: FoxESS-reported SOC **36%**, bounded physical SOC **35.021%**, independent simulated SOC **43.6%**. Final guarded target **6.071 kW**, physically capped AC exportable budget **4.487 kWh**, raw forecast path **7.727 kWh** (pre-budget; must not display as physically exportable). 60-scan mean **3.500 seconds**, p95 **5.630 seconds**, recent scan **3.319 seconds**. Zero coordinator exceptions, 27 passed commissioning checks, verified Power Down physical export **4.676 kWh**. Selected Agile export cap **7 kW**.

## Stability and removable work — review

- **Already disabled:** `detailed_comparisons_enabled=false` (confirmed by user's runtime configuration); do not turn on heavy 30-day multi-scenario replay merely for the dashboard.
- **Already decoupled:** lightweight `scenario_replay.mode=baseline_only` runs in a Home Assistant executor approximately every **300 s**, duration around **0.331 s**, and live control does **not** await it. No material stability win in disabling it today; retains No-KEMS comparison.
- **Still necessary:** actual/simulated daily bookkeeping, the Agile live optimizer, physical SOC tracking, commissioned power-balance validation, export limit, EV gate, and settlement verification. These must not be disabled or replaced by simulated values.
- **Potential future optimization:** historical Agile day comparisons (87 cached historical days, around **1.278 s** of the Agile stage per current scan) could be refreshed asynchronously at lower cadence *only* after adding reliable history corrections/price change invalidation and ensuring control does not depend on the results. Do not add a throttle without tests.
- **Historical retention:** rolling `history_days` is 90 configured; historical Agile availability is separately maintained for longer comparisons. Do not reduce it merely to save work without checking data quality.
- **Dashboard-only hiding:** removing a simulation card from the UI does not stop the underlying controller planning/replay. For stability, prefer profiling and isolating expensive reporting from live control over deleting safety-relevant modules.

## Shipping scope

Only the reporting publisher `agile_slots_state.py`, the source + packaged main dashboards, release version and tests change. No coordinator, simulation engine, export/EV/Power Down/Happy Hour control implementation, physical guard or FoxESS service write path is modified. On missing or stale evidence, physical presentation values stay unavailable rather than falling back to simulated metrics. No HA install outside the established 06:00–06:30 safe window or during active export.
