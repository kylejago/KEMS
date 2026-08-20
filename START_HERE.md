# Start here — KEMS Alpha7 platform

KEMS is currently in the **Observe → Learn → Advise → Simulate → Shadow → Control** engineering sequence. Alpha7.36 keeps that safety lifecycle internally while presenting normal users with a much simpler product model.

## Current coordinated versions

- KEMS / Home Assistant integration: `0.7.0-alpha7.36`
- Managed Home Assistant dashboard: `0.7.0-alpha7.36`
- Managed ESPHome panel: `0.7.0-alpha7-panel6`
- KEMS property Web / Pi agent: `0.7.0-alpha7-web.13`
- Public `kems.uk` source: `0.7.0-alpha7-web.13` via GitHub Actions → IONOS SFTP

## Four simple KEMS types

Normal users choose one capability level rather than a long list of simulation strategies:

1. **Live Data** — actual property monitoring only. Simulation and KEMS control are disabled.
2. **Battery & Solar** — live and simulated battery/solar optimisation using the configured import and export tariffs.
3. **Full KEMS** — forecast-aware whole-home optimisation with smart import tariff support, EV awareness and reserve planning.
4. **Full KEMS Agile** — Full KEMS plus dynamic smart-export optimisation such as Octopus Agile Outgoing.

The normal mode selector is **Live / Simulate / Control**. Shadow remains an engineering commissioning stage and is intentionally hidden from the normal user workflow.

## Managed dashboard

Alpha7.36 presents ten user-focused pages:

- Home
- Live Data
- Battery & Solar
- Full KEMS
- Full KEMS Agile
- Compare
- Cost & ROI
- History
- Advanced / Test Lab
- System

Battery & Solar, Full KEMS and Full KEMS Agile each put **Live** and **Simulated** results side by side. The Compare page presents all four KEMS types against the same household demand with common current-flow, daily energy, cost, export-income, SOC and savings metrics plus a 24-hour cost graph.

Alpha7.36 also adds a user-facing **Winner by period** table. It compares Battery & Solar, Full KEMS and Full KEMS Agile on one common bill basis: import cost minus export income. The table covers today, yesterday, seven days, 30 days, rolling 365-day Agile evidence and all tracked Agile evidence. Where an older strategy does not have a matching long-window replay, the dashboard shows a dash rather than inventing a result.

The dedicated **Cost & ROI** page separates actual measured costs from simulated costs. It shows today/week/month/year/all-tracked actual-vs-modelled totals, predicted ROI before commissioning, and the permanent actual value/ROI/payback fields that begin filling when the physical system is commissioned and operating.

Existing forecast, Agile, Power Down, EPS, commissioning, history and diagnostic content is reorganised under these pages rather than removed. Deterministic virtual stress scenarios remain available under **Advanced / Test Lab** and are disabled by default as a diagnostic entity.

## Comparison-data completeness

Alpha7.36 removes misleading dashboard dashes when KEMS already holds the value. In particular, the Compare page now reads observed import cost from the native KEMS period ledger, and Full KEMS Agile battery SOC comes from the same coherent current-routing snapshot used by the Agile dashboard and Panel6.

Physical fields that genuinely cannot exist yet — for example live battery SOC before battery commissioning — are labelled as awaiting the relevant hardware data rather than being presented as a calculation failure.

## Cheap-window handover

Alpha7.34 made the configured overnight schedule the only cheap-control authority and correctly changes the core control plan to cheap import/Force Charge with deliberate export blocked.

Alpha7.35 fixed the Agile **current-routing display** at that boundary. Once the configured overnight window opens, the reporting path immediately follows the cheap-period simulation, suppresses any stale rolling export candidate and labels the active slot as cheap overnight import/charge. This remains reporting-only and does not alter the proven Agile optimiser or hardware command policy.

## Panel6

Panel6 now exposes the same four simple choices as the main KEMS product model:

- Live Data
- Battery & Solar
- Full KEMS
- Full KEMS Agile

The older panel-only choices such as No system, Solar only, KEMS no-export, Full KEMS Forecast, Agile Smart Export and Full Island Mode have been removed from the normal panel selector. Those engineering comparisons remain available in Home Assistant where they belong.

Full KEMS Agile no longer consumes the older compact scenario snapshot. Alpha7.36 republishes the final coherent Agile `current_routing_snapshot` in the ESPHome compact protocol, so the panel and Home Assistant dashboard use the same grid import/export, solar, battery-to-home, battery-export and simulated-SOC decision.

Existing KEMS-managed panels continue to use automatic ESPHome OTA/version verification; Alpha7.36 targets `0.7.0-alpha7-panel6` and should update an already-managed panel automatically after the KEMS restart.

## Safety boundary

Alpha7.36 does **not** enable real FoxESS writes. Alpha7.31's solar-aware shared-inverter dispatch remains the proven base, with Alpha7.34's latest-safe-start/deadline protection layered above it. The 7 kW shared inverter ceiling, 10% reserve, 13-point independent command validator and strict replay remain authoritative.

Physical control remains blocked until commissioned hardware mappings, battery/grid direction, site limits and the vendor backend pass commissioning.

The hardware-control contract is vendor-neutral so FoxESS can be proven first and future Alpha ESS support can implement the same KEMS policy interface without forking the optimiser.

## Development checks

Run the repository checks before merge/release:

```powershell
.\.venv\Scripts\Activate.ps1
python -m black --check --diff .
python -m ruff check .
python -m pytest
python -m compileall -q custom_components tests
```

GitHub Actions additionally validates the packaged managed dashboard, hassfest and HACS metadata.

## Key documentation

- `README.md` — current KEMS overview
- `docs/agile-smart-export.md` — canonical Agile Smart Export behaviour
- `docs/hardware-backend-contract.md` — vendor-neutral hardware adapter contract
- `docs/commissioning-checklist.md` — physical-system commissioning gates
- `docs/control-boundary.md` — real-control safety boundary

Historical one-release validation documents remain under `docs/`; this file and `docs/agile-smart-export.md` are the current entry points.
