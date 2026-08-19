# Start here — KEMS Alpha7 platform

KEMS is currently in the **Observe → Learn → Advise → Simulate → Shadow → Control** engineering sequence. Alpha7.35 keeps that safety lifecycle internally while presenting normal users with a much simpler product model.

## Current coordinated versions

- KEMS / Home Assistant integration: `0.7.0-alpha7.35`
- Managed Home Assistant dashboard: `0.7.0-alpha7.35`
- Managed ESPHome panel: `0.7.0-alpha7-panel5`
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

Alpha7.35 consolidates the managed dashboard to nine user-focused pages:

- Home
- Live Data
- Battery & Solar
- Full KEMS
- Full KEMS Agile
- Compare
- History
- Advanced / Test Lab
- System

Battery & Solar, Full KEMS and Full KEMS Agile each put **Live** and **Simulated** results side by side. The Compare page presents all four KEMS types against the same household demand with common current-flow, daily energy, cost, export-income, SOC and savings metrics plus a 24-hour cost graph.

Existing forecast, Agile, Power Down, EPS, commissioning, history and diagnostic content is reorganised under these pages rather than removed. Deterministic virtual stress scenarios remain available under **Advanced / Test Lab** and are disabled by default as a diagnostic entity.

## Cheap-window handover

Alpha7.34 already made the configured overnight schedule the only cheap-control authority and correctly changes the core control plan to cheap import/Force Charge with deliberate export blocked.

Alpha7.35 fixes the Agile **current-routing display** at that boundary. Once the configured overnight window opens, the reporting path immediately follows the cheap-period simulation, suppresses any stale rolling export candidate and labels the active slot as cheap overnight import/charge. This is reporting-only and does not alter the proven Agile optimiser or hardware command policy.

## Panel5

Panel5 remains unchanged in Alpha7.35. When battery energy is exported, the battery-to-house connector animates even when truthful `battery_to_home` is zero, because the central house icon represents the shared AC bus before energy continues to the grid.

Existing KEMS-managed panels continue to use automatic ESPHome OTA/version verification when a future panel version changes.

## Safety boundary

Alpha7.35 does **not** enable real FoxESS writes. Alpha7.31's solar-aware shared-inverter dispatch remains the proven base, with Alpha7.34's latest-safe-start/deadline protection layered above it. The 7 kW shared inverter ceiling, 10% reserve, 13-point independent command validator and strict replay remain authoritative.

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
