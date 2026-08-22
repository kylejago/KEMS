# KEMS 0.8.0-alpha8.2

Alpha8.2 is a coordination-only maintenance release over Alpha8.1. It does not add a new Home Assistant runtime behaviour or enable hardware control. Its purpose is to publish a fresh immutable coordinated bundle that moves the KEMS Web / Pi / PWA train to the already-validated `0.8.0-alpha8-web.1` release without modifying the existing Alpha8.1 release.

## Coordinated components

- KEMS HA / dashboard: `0.8.0-alpha8.2`
- KEMS Web / Pi / PWA: `0.8.0-alpha8-web.1`
- Public KEMS Web: `0.8.0-alpha8-web.1`
- ESP32 panel: `0.8.0-alpha8-panel.0` (unchanged)

## Scope

- Advances the canonical Home Assistant release identity so the automatic KEMS updater can discover a new immutable coordinated release.
- Advances the property Web and Pi-agent bundle targets from `0.8.0-alpha8-web.0` to `0.8.0-alpha8-web.1`.
- Advances the optional public-Web bundle target to the same Web release.
- Keeps the managed panel release unchanged.
- Keeps implementation modules functionally named; the Alpha8.2 identifier describes this repository/release state, not Python implementation filenames.

## Safety

This release does not enable real inverter control. Hardware writes remain blocked, shadow remains the maximum permitted stage, and physical commissioning is still required before any future control release.
