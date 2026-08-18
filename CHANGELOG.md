## 0.7.0-alpha7.5 — Agile Smart Export

- Added **Agile Smart Export** as a separate simulation/shadow strategy using actual Octopus Agile Outgoing half-hourly export prices for electricity region L.
- Discovers the active Agile Outgoing product and Region L tariff/rate endpoint instead of permanently hard-coding an Octopus product version.
- Persists VAT-inclusive half-hour prices with product code, tariff code and exact valid-from/valid-to timestamps; handles 46/48/50-slot UK DST days and reports today/tomorrow price completeness.
- Added price-aware battery export timing that holds exportable battery energy for the highest-value remaining Agile slots while enforcing battery capacity/SOC reserve, charge/discharge efficiency, KH7 inverter limit, export limit, site-import limit and forecast reserve protection.
- Added price-aware surplus-solar storage: KEMS stores solar only when reserve protection needs it or a later Agile export opportunity remains more valuable after round-trip losses and the battery-wear allowance.
- Prevents Agile optimisation from deliberately creating avoidable expensive day-rate import merely to preserve battery energy for later export, and avoids deliberate export into negative Agile slots where storage/curtailment is available.
- Retains the 12p/kWh fixed-export benchmark alongside Agile results and tracks the same-dispatch gain/loss from Agile pricing.
- Added a 2p per discharged kWh battery-wear allowance to the economic strategy comparison for both Full KEMS Forecast and Agile Smart Export, while retaining raw energy-only cost separately.
- Added today, tomorrow, yesterday, 7-day, 30-day and all-time strategy summaries with winner, winning margin, import/export, solar/battery routing, export income and weighted achieved Agile rate.
- Added a forecast replay for tomorrow using KEMS learned hourly house demand, fused solar forecast and the normal Intelligent cheap window; unannounced extra Intelligent slots are deliberately not invented.
- Added a dedicated managed built-in dashboard named **Full KEMS Forecast vs Agile Smart Export**, including live Region L price, slot-by-slot planned actions, strategy economics, cumulative comparison and data-quality status.
- Added diagnostics and persistent daily comparison history. Settled history is backfilled once, then the live replay is throttled and only yesterday/today are re-evaluated to avoid repeated full-history work.
- Agile Smart Export remains **simulation only** and adds no FoxESS write path; real control remains behind the existing commissioning and safety boundary.

## 0.7.0-alpha7 - cross-midnight SOC continuity

- Fixed live simulation day-start SOC so the previous day’s full simulated battery state is carried across midnight instead of resetting to the configured initial SOC before replaying only the cheap-period tail.
- Replays retained previous-day battery behaviour recursively across available history, while still allowing a real observed battery SOC to anchor the simulation when one exists.
- Closes the final pre-midnight interval when the next-day boundary sample is within the normal 30-minute integration cap; larger data gaps carry the last simulated state without inventing extra charge or discharge.
- Preserves carried SOC immediately after midnight even when only one new-day history sample exists.
- Caches completed day-start replays by configuration/history boundary so normal coordinator updates do not reprocess the full retained history every minute.
- Added regression coverage for the former 57.9% overstatement case and the first-sample-after-midnight reset.
- Real FoxESS writes remain hard-blocked.
- Added **Full KEMS Forecast** as a seventh parallel profile and sixth financial scenario while leaving Full KEMS unchanged as the profit-first benchmark.
- Added Forecast.Solar auto-discovery plus a direct, cached Open-Meteo UKMO multi-array tilted-irradiance provider for the proposed East/West/South PV geometry.
- Added conservative forecast fusion, provider agreement/confidence reporting, and hourly solar-shape scaling to the fused production total.
- Added learned remaining-today, tomorrow-total and 24-hour house-demand forecasts.
- Added physical recharge feasibility: overnight charge capacity, maximum achievable morning SOC, full-charge feasibility, additional cheap time to full, forecast-required morning SOC, recharge shortfall and minimum pre-cheap SOC.
- Added hourly forward energy simulation so late-arriving winter solar cannot hide a morning battery shortfall behind a reassuring daily total.
- Added Normal, Watch, Protect and Recovery forecast states. Protect retains only the calculated battery energy needed to avoid predicted day-rate import; Recovery uses solar for home/battery only until the reserve target is restored, then resumes Full KEMS export behaviour.
- Forecast decisions are stamped onto retained snapshots so historical Full KEMS Forecast replay uses the decision actually known at the time rather than applying today's forecast retrospectively.
- Added forecast settings, diagnostics, scenario cost/flow carriers and explainable Home Assistant sensors. Open-Meteo failures use cached data and never disable normal KEMS analysis.

## 0.7.0-alpha6 — parallel scenario comparison

- Added source-specific tariff freshness gating so stale Intelligent-slot signals cannot authorise cheap charging; tariff inputs now fail back independently without making fresh power telemetry stale.
- Tuned the slower Octopus Intelligent slot/schedule sources to a 360-second freshness window while retaining the normal 180-second timeout for live power and fast tariff inputs.

- Added a dedicated what-if replay engine that evaluates six independent system designs from the same retained observations: No system, Solar only, Solar + battery, KEMS no-export, Full KEMS smart control, and Full island mode — grid down.
- Comparison replay is independent of the currently selected export-tariff/live-readiness mode, so no-export can remain active while paid-export Full KEMS is still modelled in parallel.
- Added exact today cost, import/export, solar routing, battery routing, end-SOC, standing-charge and saving-vs-baseline summaries for every scenario.
- Added an explainable saving decomposition: reduced day-rate import, change in cheap-rate import, export income, and Power Down income.
- Added a resilience-only full-island replay with grid import/export forced to zero, EPS output limits, emergency-floor protection, outage survival, unserved energy and first-shortfall reporting; it is excluded from cheapest-scenario financial ranking.
- Full Island Mode now deliberately blocks EV charging before EPS replay, reports that EV energy as intentionally shed rather than unserved house load, and measures resilience against the remaining island/EPS demand.
- Added prepared-outage resilience on top of Full Island Mode: KEMS now finds the minimum starting SOC needed to eliminate energy-limited shortfall, adds a 5% preparation margin, and replays the outage from that prepared target without pretending a larger EPS or any non-EV load-shedding capability exists.
- Prepared resilience explicitly distinguishes an unavoidable EPS-limit shortfall from an energy-capacity shortfall, and reports when even 100% SOC cannot cover the requested outage period.
- Fixed Power Down completion auditing so joined/pre-session samples no longer permanently fail the EV-block check; safety evidence is now accumulated only while the session is actually active, with explicit plan, EV, island-override, and no-active-sample completion reasons.
- Added cumulative midnight-to-now cost timeline data for the five financial scenarios, plus island SOC/load-served/unserved-energy/status timeline data.
- Added Yesterday, 7-day and 30-day retained-history scenario rollups.
- Added smart-simulation cheap/day import-cost splits and solar/grid-to-battery flow accounting used by the comparison engine and diagnostics.
- Added built-in and ApexCharts/Mushroom Compare dashboards.
- Full KEMS and no-export comparison batteries are carried independently across retained days, keeping scenario histories isolated from one another.
- Real FoxESS writes remain hard-blocked.

## 0.7.0-alpha5 — awaiting export tariff / no-export live readiness

- Added an explicit Export tariff status: Active or Not active / awaiting export tariff.
- Awaiting mode values export at 0p/kWh and overrides normal export settings without deleting the configured future export rate.
- Forces self-consumption-first simulation: solar → home → battery, then battery → home, with deliberate grid export disabled.
- Adds solar-aware cheap-period charging targets so the battery retains forecast home cover while leaving conservative PV headroom.
- Power Down remains visible but no battery/export reserve is created while paid export is unavailable; reduction can still come from avoiding import.
- Added export-tariff/no-export status, solar-to-battery flow and overnight charge-target diagnostics.
- Control Lab mirrors the policy in shadow planning but real hardware writes remain hard-blocked.
- Existing alpha4 users migrate with Export tariff status = Active so behaviour does not silently change.

## 0.7.0-alpha4 hotfix — actual lifetime reconciliation

- Makes the persisted daily ledger authoritative for observed/pre-install lifetime energy and billing totals, matching the simulated-ledger approach.
- Corrects stale-source high-water contamination such as frozen live-demand intervals that were later excluded from a day.
- Reconciles house consumption, grid import/export, solar/battery energy, gas, import/export cost and simulated totals on load and every update.
- Deliberately leaves commissioned-only actual system-value counters on their existing commissioning-gated accumulation path.
- Keeps incomplete-day flags intact rather than silently treating repaired history as complete.
- Real hardware writes remain unavailable.

## 0.7.0-alpha4 hotfix — stale live-source protection

- Detects stale live power/SOC sources using Home Assistant `State.last_reported`.
- Uses the existing configurable stale-data timeout (default 180 seconds).
- Stops integrating frozen power values into consumption, cost, learning and simulation totals.
- Marks reporting periods incomplete when stale/missing intervals reduce day coverage.
- Lowers Data Quality and exposes the exact stale logical fields and source ages.
- Makes Control Data Fresh fail safe from underlying source age, not merely the new KEMS snapshot timestamp.
- Adds source report timestamps/ages to diagnostics for troubleshooting connectivity outages.
- Real hardware writes remain unavailable.

## 0.7.0-alpha4

- Fixed blank settings-menu labels when Home Assistant or the browser retained an older custom-integration translation bundle.

# Changelog

## 0.7.0-alpha4 — guided setup and editable tariff UI

- Replaced the single oversized options form with a six-page Home Assistant Configure menu.
- Added automatic tariff mode with user-editable day-rate, off-peak-rate, standing-charge, export-rate, and cheap-period fallback values.
- Added manual tariff mode for users without a supported live tariff integration.
- Added local-time cheap-period start/end controls with correct overnight handling across midnight.
- Preserved confirmed Intelligent extra-slot safety: the cheap rate is used only when the Intelligent slot and active EV charging agree.
- Added guided first-time setup for automatic versus manual tariff selection.
- Allowed manual-tariff installations to run without a current-import-rate entity.
- Split battery, solar/export, financial, monitoring, and Control Lab settings into focused pages with descriptive selectors and units.
- Added alpha3-to-alpha4 migration defaults without changing existing automatic Octopus behaviour.
- Fixed Home Assistant 2026.8 config-flow import failure by using supported high-precision number-selector steps.
- Added tariff-resolution and UI-schema regression coverage; 107 tests pass.
- Real FoxESS and charger writes remain disabled.

## 0.7.0-alpha3 hotfix — simulated period reconciliation

- Made the persisted daily ledger authoritative for all simulated lifetime totals.
- Corrected Month, Year, and All-time export, battery-export, and export-income differences caused when intraday simulation forecasts revised downward.
- Reconciles stored alpha3 totals immediately on load and after every accumulation update without changing actual observed totals.
- Added regression coverage for daily-ledger summation and downward simulated-export revisions.
- Real hardware writes remain disabled.

## 0.7.0-alpha3 — KH7 topology, retained Power Down results, and accumulator repair

- Separated the 7kW battery charge/discharge limits, 7kW combined KH7 AC output limit, 7kW island/EPS limit, and an independently configurable whole-site import limit.
- Modelled grid bypass correctly so a 2kW home plus 7kW battery charge is a valid 9kW site import when the installer-confirmed site limit permits it.
- Enforced `solar AC + battery AC <= 7kW` during paced export, Power Down, high-solar operation, island operation, and restoration planning.
- Restricted EPS utilisation and warning thresholds to islanded operation; grid-connected demand now uses bypass/site-import diagnostics instead.
- Added battery-charge, total KH7 output, grid-bypass, total-site-import, limit, and headroom entities for clearer dashboards.
- Persisted a separate last-completed Power Down result after Octopus removes the live event, including SOC, planned energy, maximum output, reward estimates, EV blocking, and completion status.
- Repaired the lifetime accumulator so observed electricity, gas, import/export, and bill evidence accumulate before commissioning while actual system-created value remains commissioning-gated.
- Added native Today, Week, Month, Year, and All-time summaries with separate actual/simulated totals and explicit incomplete-day reporting.
- Prevented a mid-day commissioning change from claiming modelled value created before the physical system was commissioned.
- Added an alpha2 ledger migration that rebuilds recoverable observed totals from retained history without double-counting the temporary single-import-source mapping.
- Added accumulator health, rollover, historical-repair, site-limit, KH7-headroom, EPS-status, and retained Power Down diagnostics.
- Expanded the deterministic safety suite from 12 to 15 checks and added topology, site-import, high-solar, and island-cap regression tests.
- Real FoxESS writes remain hard-blocked: backend available, commands permitted, system commissioned, and control enable all remain off by default.
- Added native Today, Week, Month, Year, and All-time summaries with separate actual/simulated totals and explicit incomplete-day reporting.
- Prevented a mid-day commissioning change from claiming modelled value created before the physical system was commissioned.
- Added an alpha2 ledger migration that rebuilds recoverable observed totals from retained history without double-counting the temporary single-import-source mapping.
- Added accumulator health, rollover, historical-repair, site-limit, KH7-headroom, EPS-status, and retained Power Down diagnostics.
- Expanded the deterministic safety suite from 12 to 15 checks and added topology, site-import, high-solar, and island-cap regression tests.
- Real FoxESS writes remain hard-blocked: backend available, commands permitted, system commissioned, and control enable all remain off by default.
