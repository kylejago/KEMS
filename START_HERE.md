# Start here — source isolation and observed-export correction

This package is prepared for:

```text
feature/source-isolation-and-observed-export-fix
```

It is KEMS `0.6.0-alpha2`. It automatically removes unsafe mappings from the
existing config entry and starts fresh KEMS learning and lifetime-ledger storage
under `clean_v6_alpha2`.

## Upload with GitHub Desktop

1. Switch to `develop` and pull the latest changes.
2. Create `feature/source-isolation-and-observed-export-fix`.
3. Extract this ZIP elsewhere.
4. Copy everything inside its top-level folder into the repository root,
   replacing the existing files but preserving the hidden `.git` directory.
5. Open the repository in VS Code.

## Local validation

```powershell
.\.venv\Scripts\Activate.ps1
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

## Commit

```text
fix: isolate observed sources from KEMS simulation outputs
```

## Home Assistant update

A full uninstall is not required. After merging into `develop`:

1. Install the exact new `develop` commit SHA with `update.install`.
2. Restart Home Assistant.
3. KEMS migrates the existing entry, removes unsafe source mappings, and starts
   fresh alpha2 internal history automatically.
4. Confirm `sensor.kems_source_validation` reports either `OK` or lists mappings
   that were rejected and removed during this startup.
5. Replace the diagnostic dashboard YAML with the alpha2 version.

Home Assistant Recorder may still display old alpha1 graph history for entity IDs,
but current KEMS calculations use only the fresh alpha2 internal dataset.
