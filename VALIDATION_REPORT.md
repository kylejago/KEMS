# KEMS validation report

Build: `0.6.0-alpha1`  
Feature branch: `feature/clean-install-diagnostics-autodiscovery`  
Scope: read-only **Observe → Learn → Advise → Simulate** plus ROI and lifetime accounting

## Automated checks completed in the build environment

- 38 Pytest tests passed.
- Python syntax was parsed for all runtime and test files without writing cache files.
- All JSON files parsed successfully.
- All dashboard, example and workflow YAML parsed successfully.
- The supplied Octopus Energy, Octopus Intelligent and Ohme inventory produced
  17 automatic mappings with no ambiguous fields.
- Exact discovery tests cover tariff, off-peak, Intelligent slots, gas, Ohme,
  house load and pre-install grid import.
- Grid tests cover positive import, signed export, duplicate signed sources and
  separate positive import/export sources.
- Grid import and export are always non-negative magnitudes; net power is import
  minus export.
- The package uses the fresh `clean_v6` history and lifetime storage namespace.
- The all-entities diagnostic dashboard dynamically lists current KEMS sensors,
  binary sensors and update entities.
- Downloadable diagnostics include configured mappings, raw source states, all
  KEMS entity states, grid normalisation details and calculation outputs.
- Package-layout tests confirm KEMS remains a hub and no absolute `kems_core`
  imports are present.
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

Do not merge until all checks are green.
