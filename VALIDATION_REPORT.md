# Validation report

Build: `0.7.0-alpha5`
Branch: `release/0.7.0-alpha5-no-export-live-readiness`

Validated in the isolated build environment:

- `129 passed` with pytest.
- All 65 repository Python files parse successfully with `ast.parse`.
- Home Assistant manifest and English translation JSON parse successfully.
- `git diff --check` reports no whitespace errors.
- Config-entry schema advances to version 13.
- Existing alpha4 entries migrate with `export_tariff_status = active`, preserving their existing behaviour.
- Awaiting-export mode uses an effective export rate of 0p/kWh without deleting the configured future export rate.
- Awaiting-export mode forces effective `self_use` strategy and disables deliberate battery export even when the normal battery-export option remains enabled.
- Surplus simulated PV is routed to the battery before curtailment; simulated grid export remains zero.
- Confirmed cheap periods use a forecast-derived battery target rather than automatically filling to 100% while awaiting an export tariff.
- Remaining house demand inside the active cheap window is excluded from that overnight battery target when the cheap-period end is known, because the house is served by cheap grid power during that interval.
- Future PV receives only conservative credit: 50% of forecast PV, capped at 50% of forecast home demand, then a 10% home-demand safety factor is applied.
- A provider-reported off-peak start that is already in the past is replaced with the next configured normal cheap-period start so overnight planning always has a future horizon.
- Power Down cannot re-enable battery/grid export while the export tariff is awaiting; import reduction can still be modelled.
- Control Lab mirrors no-export behaviour, uses Self Use outside cheap periods, and uses the simulation's reduced grid-charge request during cheap periods.
- Existing stale-source protection, daily/lifetime reconciliation, KH7 7kW topology, and 15/15 control preflight regressions remain covered.
- Real FoxESS and charger writes remain hard-blocked.
- `pyproject.toml`, the Home Assistant manifest, and runtime constants identify `0.7.0-alpha5` / `0.7.0a5`.

Black, Ruff, and pre-commit are not installed in this isolated execution environment. Run the repository's normal development checks after applying the patch and before merging.
