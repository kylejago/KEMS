# KEMS 0.7.0-alpha6 development steps

1. Update local `develop` and create `release/0.7.0-alpha6-scenario-comparison`.
2. Apply the supplied context-free alpha6 overlay or patch.
3. Run Black, Ruff, pytest and pre-commit.
4. Commit as `feat: add parallel scenario comparison`.
5. Push the release branch and install that branch/commit in Home Assistant.
6. Restart Home Assistant and confirm KEMS reports `0.7.0-alpha6`.
7. Confirm these five cost entities appear: No system, Solar only, Solar + battery, KEMS no-export and Full KEMS.
8. Open the shipped Compare dashboard and confirm the midnight-to-now replay graph populates.
9. Keep Export tariff status on whichever live-readiness mode is actually required; scenario replay stays independent of it.
10. Download diagnostics and confirm `scenarios.periods.today` contains all five scenarios plus a timeline.
11. Keep real control disabled until the commissioned FoxESS backend is separately mapped and verified.
