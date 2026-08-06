# KEMS 0.7.0-alpha4 development steps

1. Update local `develop` and create `release/0.7.0-alpha4-user-settings`.
2. Apply the supplied patch or copy the package over the repository root while preserving `.git`.
3. Run Black, Ruff, pytest, and pre-commit.
4. Commit as `feat: add guided setup and editable tariff UI`.
5. Push the release branch for live Home Assistant testing.
6. Install the exact alpha4 release-branch commit in Home Assistant.
7. Open **Settings → Devices & services → KEMS → Configure** and verify all six settings pages.
8. Test automatic pricing, manual pricing, an overnight cheap period, and a confirmed Intelligent extra slot.
9. Keep real control disabled until the commissioned backend is separately implemented and verified.
