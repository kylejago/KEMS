# KEMS 0.7.0-alpha3 development steps

1. Update local `develop` and create `release/0.7.0-alpha3`.
2. Copy this package over the repository root, preserving `.git`.
3. Run Black, Ruff, pytest, and pre-commit.
4. Commit as `feat: build KEMS 0.7.0-alpha3 KH7 topology`.
5. Push the release branch for live Home Assistant testing.
6. Install the exact alpha3 release-branch commit in Home Assistant.
7. Keep `operating_mode=simulate`, `control_enabled=false`, `system_commissioned=false`, and `emergency_stop=false`.
8. Re-run Power Down, night-outage, daylight-outage, emergency-stop, grid-flapping, and normal scenarios.
9. Do not merge 0.7 control work into `main` until the full scenario matrix and commissioning checks pass.
