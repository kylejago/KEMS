# Validation report

Build: `0.7.0-alpha4`
Branch: `release/0.7.0-alpha4-user-settings`

Validated in the build environment:

- `108 passed` with pytest.
- All 42 shipped Python modules parsed and compiled successfully.
- Home Assistant manifest and English translations parsed successfully.
- `git diff --check` reports no whitespace errors.
- Existing alpha3 entries migrate to automatic tariff mode without changing live Octopus pricing behaviour.
- Automatic mode prefers live Home Assistant tariff values and uses editable manual values only when a live field is unavailable.
- Manual mode works without a current-import-rate entity.
- Manual day, off-peak, standing-charge, export-rate, start-time, and end-time settings are persisted through the config-entry options flow.
- High-precision tariff and gas-conversion fields use Home Assistant 2026.8-compatible `step: any` number selectors.
- Overnight cheap periods that cross midnight resolve correctly.
- Confirmed Intelligent extra slots use the cheap rate only when the Intelligent slot and active EV charging agree.
- The options flow is split into six focused pages and preserves settings from other pages when one category is saved.
- The settings menu includes explicit fallback labels, so stale frontend translation caches cannot produce blank menu rows.
- Battery, inverter, site-import, solar/export, ROI, monitoring, Control Lab, and EPS settings remain available.
- Alpha3 accumulator repair, period reconciliation, KH7 topology, and 15/15 control preflight behaviour remain covered by the suite.
- No Python bytecode, `__pycache__`, or pytest cache directories are included.
- Real FoxESS and charger writes remain hard-blocked.
- `pyproject.toml`, the Home Assistant manifest, and runtime constants identify `0.7.0-alpha4` / `0.7.0a4`.

Black, Ruff, and pre-commit are not installed in this isolated build environment. Run the repository's normal development checks after applying the patch and before merging.
