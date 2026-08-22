# KEMS 0.8.0-alpha8.1

Alpha8.1 is a maintenance release over the Alpha8.0 consolidation baseline. It
packages the post-baseline commissioning evidence work and the Full KEMS Agile
behaviour/presentation improvements into an updater-visible Home Assistant
release.

## Included since Alpha8.0

- FoxESS telemetry stability evidence and the live shadow-readiness gate.
- Read-only FoxESS physical telemetry contract evidence.
- Forecast-protected Full KEMS Agile pre-cheap SOC planning.
- Replacement-rate export floor using the configured overnight import rate.
- Conservative forecast solar-headroom re-timing of already-safe battery export.
- Full KEMS Agile projection through the existing generic simulated sensor
  contract so Pi/Web graphs and headline export/cost values agree with the Agile
  ledger when Full KEMS Agile is selected.
- Removal of the stale duplicate Python release constant; the manifest is the
  runtime release identity.

## Coordinated components

- KEMS HA / dashboard: `0.8.0-alpha8.1`
- KEMS Web / Pi / PWA: `0.8.0-alpha8-web.0` (unchanged)
- ESP32 panel: `0.8.0-alpha8-panel.0` (unchanged)

## Safety

This release does not enable real inverter control. Hardware writes remain
blocked, shadow remains the maximum permitted stage, and physical commissioning
is still required before any future control release.
