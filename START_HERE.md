# Start here — KEMS Alpha7 platform

KEMS is currently in the **Observe → Learn → Advise → Simulate → Shadow → Control** development sequence.

The Alpha7.33 release train keeps the proven Alpha7.31 Agile Smart Export shadow behaviour unchanged and updates the managed 16×16 panel to Panel5 so battery export is shown coherently through the central house/AC bus.

## Current coordinated versions

- KEMS / Home Assistant integration: `0.7.0-alpha7.33`
- Managed Home Assistant dashboard: `0.7.0-alpha7.33`
- Managed ESPHome panel: `0.7.0-alpha7-panel5`
- KEMS property Web / Pi agent: `0.7.0-alpha7-web.13`
- Public `kems.uk` source: `0.7.0-alpha7-web.13` via GitHub Actions → IONOS SFTP

## Panel5 update behaviour

Panel5 preserves the compact KEMS scenario protocol and all existing display modes. When battery energy is being exported, the battery-to-house connector now animates even when the truthful `battery_to_home` flow is zero, because the central house icon represents the shared AC bus before energy continues to the grid.

Existing KEMS-managed panels install Panel5 automatically after the KEMS/Home Assistant update restarts: KEMS synchronises the managed ESPHome YAML, queues the ESPHome Device Builder OTA and verifies the firmware version after the panel reconnects.

## Safety boundary

Alpha7.33 does **not** enable real FoxESS writes. Alpha7.31's proven Agile dispatch, inverter-headroom calculation, 10% reserve protection, 13-point independent command validator and strict candidate-applied replay remain the reference behaviour.

Physical control remains blocked until commissioned FoxESS mappings, battery/grid direction, site limits and the real backend pass commissioning.

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
- `docs/platform-release-alpha732.md` — coordinated platform-cleanup baseline
- `docs/commissioning-checklist.md` — physical-system commissioning gates
- `docs/control-boundary.md` — real-control safety boundary

Historical one-release Agile proof documents remain under `docs/` as validation history; this file and `docs/agile-smart-export.md` are the current entry points.
