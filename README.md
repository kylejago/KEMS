# KEMS

KEMS (Kyle Energy Management System) is a Home Assistant custom integration for observing home-energy data.

## Current milestone: Observe

This build is read-only. It reads selected Octopus Energy and optional Ohme entities, creates a coordinated snapshot every five minutes, and exposes KEMS sensors and binary sensors. It does not control any device.

## Installation

1. Add `https://github.com/kylejago/KEMS` to HACS as a custom **Integration** repository.
2. Download KEMS and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → KEMS**.
4. Select the Octopus entities requested by the setup form. Ohme fields are optional.

## Development checks

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check .
python -m pytest
python -m compileall -q custom_components tests
```

Every file required at runtime is inside `custom_components/kems`, because HACS installs only that directory. GitHub Actions also run HACS and hassfest validation.
