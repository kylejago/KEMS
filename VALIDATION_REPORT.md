# KEMS 0.7.0-alpha6 validation report

Build: `0.7.0-alpha6`
Branch: `release/0.7.0-alpha6-scenario-comparison`

## Automated checks

- Pytest: **136 passed** in the isolated build environment.
- Dashboard YAML: validated by the KEMS dashboard regression suite.
- Python parsing/import regression tests: passed.
- HACS package-layout regression tests: passed.
- Scenario comparison regression tests cover all five scenarios, cost reconciliation, replay timeline generation and historical rollups.

Black, Ruff and pre-commit are not installed in the isolated artifact environment, so run the repository's normal local pre-commit suite before merge. The added Python source is kept within the configured 88-character line length.
