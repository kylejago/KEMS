# Start here — feature/proposal-system-simulation

This package is designed to be copied into a new feature branch while the existing Home Assistant installation continues collecting at least 24 hours of uninterrupted KEMS history.

## GitHub Desktop

1. Open the KEMS repository in GitHub Desktop.
2. Switch to `develop`.
3. Fetch and pull the latest `develop`.
4. Create a branch named:

```text
feature/proposal-system-simulation
```

5. Choose **Repository → Show in Explorer**.
6. Delete the repository contents except the hidden `.git` directory.
7. Extract this ZIP elsewhere.
8. Copy everything from inside the extracted folder into the repository root.
9. Open the repository in VS Code.

## Local environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pre_commit install
```

## Validation

```powershell
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Pre-commit may change files on its first pass. Repeat the validation commands until all checks pass.

## Commit

```text
feat: add proposal simulation gas tracking and energy dashboards
```

Publish the branch and open a pull request into `develop`. It can be merged once GitHub checks are green, but leave the current Home Assistant version installed until the first 24-hour observation period is complete.

## Later Home Assistant installation

After the soak test, pull the merged `develop`, obtain its full SHA with `git rev-parse HEAD`, install that SHA through `update.install`, restart Home Assistant, and use KEMS **Reconfigure** to add the newly detected gas/export/FoxESS entities.
