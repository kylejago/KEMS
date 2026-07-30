# KEMS clean branch setup

This package contains the KEMS core code inside the Home Assistant custom integration so HACS installs every required Python module.

## Create a clean branch

From a fresh clone of the repository:

```powershell
git checkout develop
git pull origin develop
git checkout -b fix/package-kems-core-clean
```

Delete the repository contents except for the `.git` folder, then copy the contents of this ZIP into the repository root.

Run the checks:

```powershell
python -m black .
python -m ruff check .
python -m pytest
```

Commit and push:

```powershell
git add .
git commit -m "fix: package kems core with integration"
git push -u origin fix/package-kems-core-clean
```

Create a pull request into `develop`. After merging, install the exact `develop` commit SHA through Home Assistant's `update.install` action, then restart Home Assistant.

## Important packaging change

The core package now lives at:

```text
custom_components/kems/kems_core/
```

Integration imports use relative package paths, so Home Assistant no longer depends on a missing top-level `kems_core` module.
