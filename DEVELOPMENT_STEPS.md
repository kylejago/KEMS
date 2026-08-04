# KEMS 0.7.0-alpha1 development steps

1. Create `feature/control-lab-and-island-simulation` from the new `develop` branch after `v0.6.0-beta1` is tagged on `main`.
2. Copy this package over the repository root, preserving `.git`.
3. Run Black, Ruff, pytest, and pre-commit.
4. Commit as `feat: add pre-installation control and island simulation lab`.
5. Merge the feature branch into `develop` only.
6. Install the exact `develop` commit in Home Assistant for simulation testing.
7. Keep `operating_mode=simulate`, `control_enabled=false`, `system_commissioned=false`, and `emergency_stop=false`.
8. Do not merge this control alpha to `main` until the scenario matrix and commissioning checks pass.
