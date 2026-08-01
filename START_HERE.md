# Start here — feature/roi-lifetime-ledger

This package is designed to replace the proposal-system feature branch with ROI, lifetime tracking, and the Home Assistant hub-classification correction. The existing KEMS history storage key remains unchanged.

## GitHub Desktop

1. Open the KEMS repository in GitHub Desktop.
2. Switch to `develop`.
3. Fetch and pull the latest `develop`.
4. Create a branch named:

```text
feature/roi-lifetime-ledger
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
feat: add ROI lifetime ledger and profit tracking
```

Publish the branch and open a pull request into `develop`. Merge only after all GitHub checks are green.

## Later Home Assistant installation

Pull the merged `develop`, obtain its full SHA with `git rev-parse HEAD`, install that SHA through `update.install`, and restart Home Assistant. KEMS should then appear under **Integrations**, not Helpers. Open KEMS options to review ROI assumptions; leave the commissioning date blank until the real system is installed.
