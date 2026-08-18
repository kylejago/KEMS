# Agile Smart Export

Agile Smart Export is a read-only KEMS simulation that compares the existing **Full KEMS Forecast** strategy with an export-price-aware strategy using the real Octopus Agile Outgoing half-hour prices for electricity region **L**.

It does not alter KEMS control commissioning and does not create a FoxESS write path.

## Price source

KEMS uses the public Octopus Energy API. It discovers the current active Agile Outgoing export product instead of permanently hard-coding a product version, then follows the Region L tariff's `standard_unit_rates` link.

For each half-hour slot KEMS retains:

- Octopus product code
- Octopus tariff code
- electricity region (`L`)
- VAT-inclusive p/kWh rate
- `valid_from`
- `valid_to`

Rates are requested with explicit UTC time bounds and retained with their source timestamps. This also allows KEMS to report 46, 48, or 50 expected half-hour slots on UK daylight-saving transition days rather than assuming every local day contains exactly 48 slots.

The price collector refreshes at most once every 15 minutes, persists successfully fetched rates, and keeps the last successful data if Octopus is temporarily unreachable.

## Simulation boundary

Agile Smart Export starts from the same KEMS observations and physical configuration as Full KEMS Forecast. It respects:

- battery capacity and reserve SOC
- maximum charge and discharge power
- charge and discharge efficiency
- inverter AC limit
- export limit
- configured site-import limit
- observed or proposal solar generation
- observed/learned house demand
- forecast minimum pre-cheap reserve protection
- forecast overnight charge target
- normal Intelligent off-peak import timing and rates

The initial battery-wear allowance is **2p per discharged kWh**. It is included in the economic comparison for both strategies so Agile does not appear to win simply by cycling the battery harder. Raw energy-only cost is retained separately.

## Dispatch logic

Outside a confirmed cheap period, Agile Smart Export uses solar for the house first and then uses the battery for remaining house demand when energy is available above the protected reserve. This prevents KEMS from deliberately creating avoidable day-rate import purely so the same battery energy can be sold later.

Surplus solar is stored when either reserve protection needs it or the best later Agile export opportunity, after charge/discharge losses and the battery-wear allowance, is worth more than exporting that solar immediately. Otherwise the solar is exported at the current Agile rate.

Exportable battery energy is reserved for the highest-value remaining Agile slots before the next normal cheap period. KEMS calculates how many half-hour slots would be required to export the remaining energy within the configured battery and inverter power limits and only deliberately exports when the current rate is inside that high-value set.

If an Agile export slot is negative, KEMS does not deliberately export into it where storage or curtailment is physically available.

During a confirmed cheap period the house can be supplied by the grid and the battery is charged toward the KEMS forecast overnight target, still respecting charge power and site-import limits. Positive-value solar can continue to export.

## Fixed 12p benchmark

The existing fixed-export benchmark is retained at **12p/kWh**. Agile Smart Export therefore records both the real Agile export income and what the same simulated export dispatch would have earned at 12p/kWh.

This is deliberately separate from the Full KEMS Forecast comparison:

- **Full KEMS Forecast vs Agile Smart Export** answers which complete strategy was better.
- **Agile vs 12p on the same dispatch** isolates the effect of the export tariff price on the Agile dispatch.

## Today, tomorrow, and history

KEMS calculates:

- Today
- Tomorrow forecast
- Yesterday
- Last 7 days
- Last 30 days
- All tracked time

Completed days are persisted so the all-time comparison grows independently of the rolling observation-history window.

Tomorrow uses the KEMS learned hourly house-demand profile and KEMS solar forecast. Because extra Intelligent charging slots are only known when Octopus/Ohme actually schedule them, tomorrow's projection uses the configured normal Intelligent off-peak window rather than inventing future bonus slots.

## Price-data quality

The comparison exposes separate counts and completeness for today and tomorrow. Tomorrow is reported as awaiting publication before the Octopus publication window, in the publication window while rates are arriving, or incomplete if the expected slots are still missing afterwards.

Agile Smart Export will not report the live strategy as ready unless today's price coverage is complete and the underlying simulation has sufficient observation coverage.

## Dashboard

Agile Smart Export is built directly into the automatically managed **KEMS Master Dashboard**. KEMS packages the specialist comparison views with the integration and appends them to `/config/kems_master_dashboard.yaml` every time the managed dashboard is refreshed.

No second Lovelace/YAML dashboard registration is required.

The master gains four Agile comparison tabs:

- **Forecast vs Agile** — current Region L Agile rate, data quality, current Smart Export action, Full KEMS Forecast vs Agile Smart Export cost/income/routing and today's winner.
- **Agile Price Plan** — today and tomorrow half-hour prices, planned actions, grid export, battery export and ending SOC.
- **Agile History** — yesterday, 7-day, 30-day and all-time winner/advantage history.
- **Agile Assumptions** — the fixed 12p benchmark, battery-wear allowance, physical constraints and read-only safety boundary.

The standalone repository file `dashboards/kems_agile_smart_export_builtin.yaml` remains available as a specialist/reference dashboard for anyone who deliberately wants a separate comparison dashboard, but KEMS does not create or register a second managed dashboard file in Home Assistant.

See `dashboards/README.md` for the one-time KEMS Master Dashboard registration.

## Diagnostics and safety

The KEMS diagnostics payload contains an `agile_smart_export` section with product/tariff discovery, current rate, data quality, period results, price-slot plans, update timestamps, and the last collection error if any.

The simulation is explicitly labelled `simulation_only`. It never calls the KEMS control backend, does not bypass commissioning, and cannot issue charge/discharge/export commands to FoxESS hardware.
