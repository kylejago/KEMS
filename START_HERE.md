# Start here — KEMS v0.6.0-beta1

This is the consolidated, read-only release candidate containing every tested fix through alpha5, including the Power Down dashboard correction.

## Branch and release

```text
release/0.6.0-beta1
```

Copy the package into the repository root, preserving `.git`, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Expected pytest result: `67 passed`.

Commit:

```text
release: prepare v0.6.0-beta1
```

Merge the release branch into `develop`, then merge `develop` into `main`. Create Git tag and GitHub release `v0.6.0-beta1` from `main`.

This beta remains the safe rollback baseline. It does not write to FoxESS, Ohme, or Octopus.
