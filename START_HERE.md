# Start here: clean branch installation

## Create the branch in GitHub Desktop

1. Select the KEMS repository.
2. Switch to `develop`, then fetch and pull.
3. Create a new branch named `fix/clean-observe-rebuild` from `develop`.
4. Open the repository in Explorer.
5. Delete the repository contents except the hidden `.git` directory.
6. Copy everything from inside this ZIP's `KEMS-clean-rebuild` folder into the repository root.

## Validate in VS Code

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check .
python -m pytest
python -m compileall -q custom_components tests
python -m pre_commit install
python -m pre_commit run --all-files
```

Commit as:

```text
fix: rebuild observe integration with clean package layout
```

Publish the branch and merge it into `develop`.

## Clean Home Assistant reinstall

1. Delete the existing KEMS config entry under **Settings → Devices & services**.
2. Remove KEMS in HACS.
3. Confirm `/config/custom_components/kems` is gone; delete it manually if it remains.
4. Restart Home Assistant.
5. Install the new branch commit through HACS, or temporarily make the clean branch the repository's default branch for testing.
6. Restart Home Assistant.
7. Add KEMS and select the requested source entities.

The installed file `/config/custom_components/kems/collector.py` must contain:

```python
from .kems_core.snapshot import Snapshot
```

There must be no top-level `/config/kems_core` folder.
