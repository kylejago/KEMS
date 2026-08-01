# Start here — clean install, diagnostics and automatic discovery

This package is prepared for:

```text
feature/clean-install-diagnostics-autodiscovery
```

It is KEMS `0.6.0-alpha1` and intentionally starts a fresh KEMS learning and
lifetime-ledger database.

## Upload with GitHub Desktop

1. Switch to `develop` and pull the latest changes.
2. Create `feature/clean-install-diagnostics-autodiscovery`.
3. Open the repository folder.
4. Delete everything except the hidden `.git` directory.
5. Extract this ZIP elsewhere and copy everything inside its top-level folder
   into the repository root.
6. Open the repository in VS Code.

## Local validation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pre_commit install

python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Repeat the checks if Black, Ruff or pre-commit modifies files.

## Commit

```text
feat: add clean install diagnostics and exact entity discovery
```

Merge into `develop` only after Validate, HACS and Hassfest are green.

## Clean Home Assistant installation

After the new branch is merged and you have copied the full `develop` SHA:

1. Remove the existing KEMS config entry from **Settings → Devices & services**.
2. Uninstall KEMS from HACS.
3. Restart Home Assistant.
4. Reinstall KEMS from HACS, then install the exact `develop` SHA if required.
5. Restart Home Assistant again.
6. Add KEMS. The first screen should show the automatically detected Octopus,
   Octopus Intelligent and Ohme mappings. Leave manual review off and confirm.
7. Import `dashboards/kems_diagnostics_all_entities.yaml` into a new dashboard.

Old KEMS storage files may remain orphaned in Home Assistant, but this build uses
a new internal `clean_v6` namespace and will not load them.
