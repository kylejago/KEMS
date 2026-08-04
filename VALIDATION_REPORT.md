# KEMS validation report

Build: `0.6.0-alpha5`  
Feature branch: `feature/octoplus-power-down-aware-export`  
Scope: read-only **Observe → Learn → Advise → Simulate** plus ROI, lifetime accounting, and Power Down-aware export planning

## Automated checks completed in the build environment

- 67 Pytest tests passed.
- All 52 Python source and test files parse successfully.
- All 3 JSON files parse successfully.
- All 14 YAML files parse successfully.
- The system profile uses the Fox ESS KH7 7kW inverter, 56.42kWh battery,
  10% reserve, and fixed 12p/kWh export rate.
- Normal battery export remains paced towards the next cheap period.
- Joined Octoplus Power Down sessions are discovered from the BottlecapDave
  event entity; legacy Saving Session entities remain supported as a fallback.
- KEMS does not join sessions or write to Octopus or inverter entities.
- Before a joined session, KEMS protects enough stored energy to cover the home
  and maximise useful session export within the 7kW inverter/export constraints.
- During an active session, the model supplies the home first and exports the
  remaining available inverter output without dropping below the 10% reserve.
- Session reward estimates use net baseline reduction, keeping the fixed 12p/kWh
  export income separate from the Power Down bonus.
- The Power Down bonus rate is calculated using the user-confirmed conversion of
  8 Octopoints = 1p.
- Optional import and export baseline sensors are supported. Estimated bonus and
  combined session income remain unavailable when no suitable baseline exists.
- Baseline incompleteness is exposed separately in diagnostics.
- A session after the next cheap period does not unnecessarily suppress current
  daytime export because the battery can recharge first.
- Existing source isolation, KH7 output limits, home-reserve fallbacks, smooth
  learning confidence, and seven-complete-day ROI gating remain covered.
- Existing observed history and learning data are preserved.
- The superseded alpha4 simulated financial ledger resets once through the
  simulation-ledger migration version.
- No `__pycache__`, `.pyc`, or `.pytest_cache` files are included in the final
  package.

## Checks required locally and on GitHub

Black and Ruff are pinned in `requirements-dev.txt` but are not available from
this build environment's package index. Run the complete local validation before
merging:

```powershell
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

HACS validation and Hassfest should also complete through GitHub Actions.
