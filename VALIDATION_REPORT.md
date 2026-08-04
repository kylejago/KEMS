# Validation report

Build: `0.6.0-beta1`
Target: `main` release candidate

Validated in the build environment:

- `67 passed` with pytest.
- 52 Python source/test files parsed successfully.
- 3 JSON files parsed successfully.
- 14 YAML files parsed successfully.
- Dashboard regression tests include the Power Down entity-ID hotfix.
- No Python bytecode or `__pycache__` directories are included.
- 99 shipped files are covered by `FILE_MANIFEST.sha256`.

Black, Ruff, and pre-commit must still be run in the Windows development environment before merging.
