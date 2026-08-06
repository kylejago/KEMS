# Start here — KEMS 0.7.0-alpha3 Control Lab

Apply this package over the current 0.7.0-alpha2 integration branch. It preserves all existing KEMS observation and simulation data.

## Development branch

```text
release/0.7.0-alpha3
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

Expected pytest result: `97 passed`.

Commit:

```text
feat: build KEMS 0.7.0-alpha3 KH7 topology
```

Push this release branch for live Home Assistant testing. Do not merge into `main` until the alpha3 Control Lab matrix passes.

Safe pre-install settings:

```text
Operating mode: Simulate
Virtual scenario: Normal
Master control enabled: Off
System commissioned: Off
Emergency stop: Off
```

Real FoxESS writes are hard-blocked in this alpha even if Control is selected.
