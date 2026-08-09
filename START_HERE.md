# Start here — KEMS 0.7.0-alpha4 guided setup

Apply this package over the current alpha3 code. It preserves existing KEMS observation, lifetime, and simulation data.

## Development branch

```text
release/0.7.0-alpha4-user-settings
```

Create it from the latest `develop` branch, apply the patch, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Expected pytest result: `106 passed`.

Commit:

```text
feat: add guided setup and editable tariff UI
```

After installing in Home Assistant, restart and open:

```text
Settings → Devices & services → KEMS → Configure
```

Verify the Tariff and prices page first. Existing users should remain in Automatic mode and continue using live Octopus rates. Real FoxESS writes remain blocked.
