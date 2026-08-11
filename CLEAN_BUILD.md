# KEMS 0.7.0-alpha6 clean build

This build is based on the final 0.7.0-alpha5 source and adds the parallel scenario-comparison engine, scenario sensors, diagnostics and Compare dashboards.

Expected validation from the supplied source:

- 136 pytest tests pass.
- All dashboard YAML parses.
- All Python source parses.
- No Python cache files are shipped.
- `FILE_MANIFEST.sha256` is regenerated after the final source tree is frozen.

Run local Black, Ruff and pre-commit before merging the release branch to `develop`.
