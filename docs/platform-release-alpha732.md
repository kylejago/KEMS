# KEMS 0.7.0-alpha7.32 — coordinated platform cleanup

Alpha7.32 packages the KEMS cleanup as one coordinated platform update rather than a sequence of unrelated component releases.

## Bundle

The release contract targets:

| Component | Target | Delivery |
|---|---|---|
| KEMS core | 0.7.0-alpha7.32 | Home Assistant / HACS |
| Managed dashboard | 0.7.0-alpha7.32 | KEMS core |
| ESP32 panel | 0.7.0-alpha7-panel4 | KEMS core / ESPHome OTA |
| Property Web | 0.7.0-alpha7-web.13 | KEMS Pi bundle agent |
| Pi agent | 0.7.0-alpha7-web.13 | KEMS Pi bundle agent |
| Public Web source | 0.7.0-alpha7-web.13 | IONOS Deploy Now / static webspace |

Panel4 intentionally remains current because Alpha7.31's Agile changes are consumed through KEMS entities and do not require a firmware-layout change.

## What is cleaned up

- replaces stale Alpha6 root build/start/validation documents with current Alpha7 entry points;
- removes obsolete one-off root build notes and the stale manually generated file manifest;
- aligns the coordinated bundle with the Alpha7 property website;
- gives the public `kems.uk` site an explicit component target without making it a required property-appliance dependency;
- makes the current Agile Smart Export document describe the proven Alpha7 shadow path rather than the original complete-horizon-only simulation.

## Behaviour freeze

No Alpha7.32 optimiser patch is installed. `agile_alpha731_solar_headroom` remains the outermost Agile runtime behaviour. This is deliberate: the cleanup release must not invalidate the non-zero proof gathered on Alpha7.31.

A later internal refactor may consolidate the historical Alpha7 patch modules, but only behind a parity harness that proves identical output to this reference baseline. Consolidation is a source-maintainability task, not a prerequisite for this coordinated user update.

## Public-site boundary

`kems.uk` is static/read-only. It must not receive Home Assistant credentials, property telemetry or a control API. Secure remote property access remains a separate future authenticated gateway and is not implemented by exposing the Pi through IONOS shared hosting.
