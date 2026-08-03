# KEMS validation report

Build: `0.6.0-alpha3`  
Feature branch: `feature/kh7-paced-export-simulation`  
Scope: read-only **Observe → Learn → Advise → Simulate** plus ROI and lifetime accounting

## Automated checks completed in the build environment

- 52 Pytest tests passed.
- All 50 Python source/test files parsed successfully.
- All 3 JSON files parsed successfully.
- All 14 dashboard/example YAML files parsed successfully.
- The proposal profile uses the Fox ESS KH7 7kW inverter, 56.42kWh battery,
  10% reserve, and 12p/kWh fixed export rate.
- Charge and discharge are capped at 7kW.
- Combined solar and battery AC output is capped at 7kW.
- Battery export is paced across the time remaining until the next cheap period.
- Live diagnostics distinguish battery-to-home power, actual battery-export power, and the unconstrained paced-export target.
- Forecast house demand is reserved before battery export is permitted.
- The 23:30-to-midnight portion of overnight charging carries into the next
  calendar day's simulated SOC.
- A six-hour 7kW cheap window at 95% efficiency is verified to reach roughly
  80.7% SOC from a 10% start rather than incorrectly forcing a full charge.
- Proposal export rates remain fixed at 12p/kWh even if another export-rate
  entity exists.
- Current simulated flow uses the current snapshot rather than a stale retained
  history sample.
- Learning confidence uses elapsed time and data coverage.
- ROI annualisation remains unavailable until seven complete 24-hour periods.
- Existing alpha2 observed history is preserved.
- The superseded simulated financial ledger resets once through a separate
  simulation-ledger migration version.
- Source isolation continues to reject KEMS outputs as observed inputs.
- No `__pycache__` or `.pyc` files are included in the final package.

## Checks required locally and on GitHub

Black, Ruff, HACS validation and Hassfest must still be run locally and through
GitHub Actions:

```powershell
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```
