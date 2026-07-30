# Start here — clean branch

This ZIP is intended to replace the full working tree of a new Git branch while keeping the repository's hidden `.git` folder.

## GitHub Desktop

1. Switch to `develop` and pull the latest changes.
2. Create a new branch named `feature/observe-learn-advise-simulate`.
3. Open the repository in Explorer.
4. Delete the existing repository contents **except `.git`**.
5. Copy everything from inside this ZIP folder into the repository root.
6. Open the repository in VS Code.

## Validate

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pre_commit install
python -m black .
python -m ruff check .
python -m pytest
python -m pre_commit run --all-files
```

Commit message:

```text
feat: add Observe Learn Advise Simulate pipeline
```

Publish the branch and open a pull request into `develop`. Do not merge until Validate, HACS, and Hassfest all pass.
