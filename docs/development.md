# Development workflow

Use `feature/* → develop → main`.

Every branch must pass:

```powershell
python -m black .
python -m ruff check .
python -m pytest
python -m pre_commit run --all-files
```

GitHub HACS and Hassfest checks must also pass before merging. Test the merged `develop` commit SHA in Home Assistant before promoting it to `main`.
