# Start here — KEMS 0.7.0-alpha2 Control Lab

Apply this package over the current 0.7.0-alpha1 `develop` branch. It preserves all existing KEMS observation and simulation data.

## Development branch

```text
fix/control-lab-validated-scenario-fixes
```

Create it from the latest `develop` branch, copy the package into the repository root while preserving `.git`, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Expected pytest result: `83 passed`.

Commit:

```text
fix: correct Power Down and island Control Lab behaviour
```

Merge this feature into `develop` only. Do not merge 0.7 control work into `main` yet.

Safe pre-install settings:

```text
Operating mode: Simulate
Virtual scenario: Normal
Master control enabled: Off
System commissioned: Off
Emergency stop: Off
```

Real FoxESS writes are hard-blocked in this alpha even if Control is selected.
