# KEMS validation report

Build: `0.5.0-alpha1`  
Feature branch: `feature/roi-lifetime-ledger`  
Scope: read-only **Observe → Learn → Advise → Simulate**

## Automated checks completed in the build environment

- 31 Pytest tests passed.
- All Python files parsed and compiled in memory successfully.
- All JSON files parsed successfully.
- All dashboard, example, and GitHub Actions YAML parsed successfully.
- Package-layout tests confirmed all runtime code is inside `custom_components/kems`.
- Relative-import tests confirmed package-relative imports resolve to shipped modules.
- No runtime source contains an absolute `kems_core` import.
- No merge-conflict markers were found.
- No `__pycache__` directories or `.pyc` files are included.
- All Python source lines are 88 characters or fewer before Black is run.
- Entity-discovery tests cover Octopus electricity/gas, Ohme, and FoxESS Modbus patterns.
- Simulation tests cover cheap-rate battery arbitrage, proposal solar, fixed 12 p/kWh export, live export-rate override, export income, baseline cost, avoided import, and system value.
- Gas tests cover direct daily totals and cumulative-meter deltas.
- Whole-home tests cover electricity-plus-gas cost and energy totals.
- ROI tests cover pre-install annualisation, actual payback, Profit Mode, operating costs, and lifetime-ledger persistence.
- Dashboard tests confirm seven valid dashboards and Live-versus-Simulated, gas, ROI, and lifetime coverage.
- The final ZIP was extracted to a clean directory and retested.

## Checks still required locally and on GitHub

Black, Ruff, HACS validation, and Hassfest were not available in this build environment. Run:

```powershell
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Do not merge until local validation and the GitHub Validate, HACS, and Hassfest checks are green.

## Deployment note

The feature can be uploaded and reviewed now. The history storage key is unchanged, so retained observations remain available. A new separate lifetime-ledger store is bootstrapped from retained history on first load. The manifest now classifies KEMS as a hub integration.

## Control boundary

This build contains no Home Assistant service calls for Octopus, Ohme, or FoxESS Modbus and does not write inverter registers or charger settings. Control remains deferred.
