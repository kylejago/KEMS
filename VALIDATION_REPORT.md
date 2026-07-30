# KEMS clean rebuild validation report

## Completed checks

- All Home Assistant runtime source is inside `custom_components/kems`.
- `kems_core` is packaged at `custom_components/kems/kems_core`.
- Runtime source contains no absolute `from kems_core ...` or `import kems_core` statements.
- Every package-relative runtime import was resolved to a source file included in the package.
- Python AST parsing passed for every Python file.
- Python bytecode compilation passed for `custom_components` and `tests`.
- JSON parsing passed for `manifest.json`, `hacs.json`, and `translations/en.json`.
- The repository contains no `__pycache__` folders or `.pyc` files at packaging time.
- Seven pytest tests passed.
- HACS and hassfest GitHub Actions are included.
- A HACS brand icon and logo are included.

## Deliberate architecture changes

- The old top-level `kems_core` package has been removed.
- User-specific hard-coded Home Assistant entity IDs have been removed.
- The config flow now asks the user to select Octopus entities and optional Ohme entities.
- The integration is observe-only and does not call any control action.
- Custom-integration English text is provided in `translations/en.json`; no core-only `strings.json` is shipped.

## Checks to run after copying to the new branch

The sandbox used to build this ZIP did not have Black, Ruff, or a complete Home Assistant runtime installed. Run these locally before committing:

```powershell
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check .
python -m pytest
python -m compileall -q custom_components tests
python -m pre_commit run --all-files
```

After pushing, confirm the **Validate**, **Validate with HACS**, and **Validate with hassfest** workflows pass on GitHub before installing the branch in Home Assistant.
