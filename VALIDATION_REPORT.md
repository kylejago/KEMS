# KEMS validation report

Build: `0.6.0-alpha2`  
Feature branch: `feature/source-isolation-and-observed-export-fix`  
Scope: read-only **Observe → Learn → Advise → Simulate** plus ROI and lifetime accounting

## Automated checks completed in the build environment

- 43 Pytest tests passed.
- Python compilation completed successfully for runtime and tests.
- All JSON files parsed successfully.
- All dashboard and example YAML files parsed successfully.
- Discovery accepts only provider-owned Octopus Energy, Octopus Intelligent,
  Ohme, and FoxESS Modbus entities.
- KEMS-generated entities and unrelated vehicle entities are rejected as inputs.
- The supplied entity inventory still produces the expected automatic source
  mappings, including the cumulative Octopus gas meter.
- Regression coverage proves proposal solar export remains simulated and cannot
  become observed export energy or income.
- Grid import and export remain non-negative magnitudes; signed net power is
  import minus export.
- The package uses the fresh `clean_v6_alpha2` history and lifetime namespace.
- Diagnostics expose accepted and rejected source mappings.
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
