# KEMS 0.7.0-alpha2 development steps

1. Update local `develop` and create `fix/control-lab-validated-scenario-fixes`.
2. Copy this package over the repository root, preserving `.git`.
3. Run Black, Ruff, pytest, and pre-commit.
4. Commit as `fix: correct Power Down and island Control Lab behaviour`.
5. Merge the fix branch into `develop` only.
6. Install the exact updated `develop` commit in Home Assistant.
7. Keep `operating_mode=simulate`, `control_enabled=false`, `system_commissioned=false`, and `emergency_stop=false`.
8. Re-run Power Down, night-outage, daylight-outage, emergency-stop, grid-flapping, and normal scenarios.
9. Do not merge 0.7 control work into `main` until the full scenario matrix and commissioning checks pass.
