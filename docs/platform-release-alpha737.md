# KEMS 0.7.0-alpha7.37 / Panel7

Alpha7.37 is a coordination release for branding and the managed 16×16 panel. It does not enable real FoxESS writes or weaken any existing control gate.

## Canonical brand

- `docs/assets/kems-logo-master.svg` is the source-of-truth full KEMS energy-system logo.
- Home Assistant/HACS may continue to use compact PNG variants where the full artwork would not remain legible.
- KEMS Web, `kems.uk`, documentation and future companion clients should derive their visual identity from the same master rather than inventing separate marks.

## Panel7 migration

Panel7 keeps the proven Panel6 rendering and routing behaviour, including the four user-facing modes:

- Live Data
- Battery & Solar
- Full KEMS
- Full KEMS Agile

The managed output is promoted to firmware target `0.7.0-alpha7-panel7` without otherwise churning the 16×16 drawing code.

A migration repair also recognises unmistakable older KEMS16x16 configs that pre-date the management header when they contain all three legacy markers: the `kems16x16` device name, Panel Firmware Version text sensor and its `panel_firmware_version` id. Those known KEMS panels can enter the automatic OTA path instead of requiring a second manual flash. Arbitrary/unrecognised local ESPHome configs remain excluded and still require explicit first adoption.

## Safety boundary

- KEMS does not create an ESPHome panel config for users who do not already have `esphome/kems16x16.yaml`.
- Automatic OTA remains restricted to an already-managed or safely recognised legacy KEMS panel.
- Firmware verification still requires the panel to reconnect and report the exact expected version.
- This release contains no real inverter or charger write-path enablement.
