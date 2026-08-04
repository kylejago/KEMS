# Validation report

Build: `0.7.0-alpha1`
Target: `develop` only

Validated in the build environment:

- `82 passed` with pytest.
- 57 Python source/test files parsed successfully.
- 3 JSON files parsed successfully.
- 15 YAML files parsed successfully.
- The control preflight reports 12/12 checks passed with default KH7 settings.
- Whole-house daylight/night outage, EPS overload, stale data, emergency stop, Power Down, cheap charge, and live-write blocking are covered by regression tests.
- No Python bytecode or `__pycache__` directories are included.
- 107 shipped files are covered by `FILE_MANIFEST.sha256`.

Black, Ruff, and pre-commit must still be run in the Windows development environment before merging into `develop`.
