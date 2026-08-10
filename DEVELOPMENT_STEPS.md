# KEMS 0.7.0-alpha5 development steps

1. Update local `develop` and create `release/0.7.0-alpha5-no-export-live-readiness`.
2. Apply the supplied patch.
3. Run Black, Ruff, pytest, and pre-commit.
4. Commit as `feat: add awaiting export tariff mode`.
5. Push the release branch and install that exact commit in Home Assistant.
6. Open **KEMS → Configure → Tariff and prices** and select **Not active / awaiting export tariff**.
7. Confirm `sensor.kems_simulation_export_rate` becomes 0p/kWh and `binary_sensor.kems_no_export_mode_active` turns on.
8. Confirm battery export and grid export targets remain zero while solar serves the home and then charges the battery.
9. During the next confirmed cheap period, confirm KEMS exposes an overnight charge target below 100% when forecast demand/solar permit it.
10. Switch Export tariff status back to **Active** and confirm the existing paced-export behaviour returns.
11. Keep real control disabled until the commissioned FoxESS backend is separately mapped and verified.
