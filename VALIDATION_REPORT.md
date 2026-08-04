# Validation report

Build: `0.7.0-alpha2`
Target: `develop` only

Validated in the build environment:

- `83 passed` with pytest.
- 57 Python source/test files parsed successfully.
- 3 JSON files parsed successfully.
- 15 YAML files parsed successfully.
- The control preflight reports 12/12 checks passed with default KH7 settings.
- Whole-house daylight/night outage, EPS overload, stale data, emergency stop, grid restoration, Power Down, cheap charge, and live-write blocking are covered by regression tests.
- Power Down now blocks EV charging during the active premium session.
- Island runtime is calculated from the current SOC down to the 10% emergency floor, while 20% remains the conservation threshold.
- No Python bytecode or `__pycache__` directories are included.
- 107 shipped files are covered by `FILE_MANIFEST.sha256`.
- Windows test discovery no longer shadows Python's standard-library `select` module with Home Assistant's `select.py` platform.
- `pyproject.toml` now matches the integration release at `0.7.0a2`.

Black, Ruff, and pre-commit must still be run in the Windows development environment before merging into `develop`.
