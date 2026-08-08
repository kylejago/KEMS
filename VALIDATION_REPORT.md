# Validation report

Build: `0.7.0-alpha4`
Branch: `release/0.7.0-alpha4-user-settings`

Validated in the build environment:

- `117 passed` with pytest.
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

## Alpha4 stale-source protection hotfix

The live-source freshness hotfix treats configured instantaneous FoxESS/grid power
and battery SOC observations as unavailable when Home Assistant has not received a
report within the configured stale-data timeout. KEMS records the source age and
stale logical fields in each snapshot, excludes intervals touching stale live data
from simulation/accounting, and uses the underlying source age for the control
fail-safe. Diagnostics expose `last_reported`, report age, and a `source_freshness`
summary. Real hardware writes remain blocked.

Hotfix verification: **115 tests passed**, repository-wide Python AST parsing passed,
`git diff --check` passed, and the release checksum manifest was regenerated and
verified. Black/Ruff/pre-commit were not available in the isolated build runtime
and should still be run in the normal Windows development environment.

## Alpha4 actual-lifetime reconciliation hotfix

The observed/pre-install lifetime energy and billing totals now rebuild from the
persisted per-day ledger plus the current-day tracking record. This removes stale
high-water contamination left by source failures that were detected after an
interval had already been accumulated. Commissioned-only actual system-value
fields are intentionally excluded so a mid-day commissioning boundary cannot be
retroactively moved to the start of the day.

Regression coverage includes the live diagnostic failure shape where the period
ledger resolves to 191.270 kWh while a stale all-time high-water value remained at
195.278 kWh. The reconciler returns the authoritative 191.270 kWh and corresponding
3,938.82 p import cost.

Final hotfix verification: **117 tests passed**. Repository-wide Python AST parsing,
JSON parsing, whitespace checks, ZIP extraction/CRC checks, and checksum-manifest
verification are performed for the release artifact. Black/Ruff/pre-commit are not
available in the isolated build runtime and should still be run in the normal
Windows development environment after applying the patch.
