# KEMS validation report

Build: `0.3.0-alpha1`  
Scope: read-only **Observe → Learn → Advise → Simulate**  
Providers: Octopus Energy, Ohme, FoxESS Modbus

## Automated checks completed in the build environment

- 15 Pytest tests passed.
- Every Python source file parsed successfully with Python's AST parser.
- Every JSON file parsed successfully.
- Every YAML workflow/example parsed successfully.
- Python bytecode compilation completed successfully.
- Package-layout tests confirmed that all runtime code is inside `custom_components/kems`.
- Relative-import resolution tests confirmed that shipped relative imports point to shipped source modules.
- No runtime code contains an absolute `kems_core` import.
- No `__pycache__` directories or `.pyc` files are included.
- All Python source lines are no longer than 88 characters before Black is run.
- Synthetic entity-discovery tests cover current Ohme status/power/battery names and FoxESS Load Power, Battery SoC, Battery Voltage, Battery Current, PV Power, Grid Consumption, and Feed-in names.
- Ohme charger-status interpretation and FoxESS battery-power derivation are unit tested.
- Extra Octopus Intelligent slots are treated as confirmed cheap only when Ohme also reports active charging.

## Checks to run after copying into the new branch

Black, Ruff, HACS validation, and Hassfest are not installed in this build container. Run the repository's normal checks locally and allow GitHub Actions to run before merging:

```powershell
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Do not merge until the Validate, HACS, and Hassfest checks are green.

## Control boundary

This build contains no Home Assistant service calls for Octopus, Ohme, or FoxESS Modbus and does not write inverter registers or charger settings. Control is intentionally deferred to a later, explicitly enabled phase.
