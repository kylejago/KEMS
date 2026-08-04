# Start here — KEMS 0.7.0-alpha1 Control Lab

Apply this package only after `v0.6.0-beta1` has been merged and tagged on `main`.

## Development branch

```text
feature/control-lab-and-island-simulation
```

Create it from the refreshed `develop` branch, copy the package into the repository root while preserving `.git`, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Expected pytest result: `82 passed`.

Commit:

```text
feat: add pre-installation control and island simulation lab
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
