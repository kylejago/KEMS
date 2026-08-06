# Validation report

Build: `0.7.0-alpha3`
Branch: `release/0.7.0-alpha3`

Validated in the build environment:

- `97 passed` with pytest.
- Corrected the alpha3 lifetime-history rebuild by importing `collections.defaultdict`.
- 61 Python source/test files parsed and compiled successfully.
- 2 JSON files parsed successfully.
- 12 YAML files parsed successfully.
- No Python source/test line exceeds 100 characters.
- `git diff --check` reports no whitespace errors.
- The default KH7 control preflight reports 15/15 checks passed.
- Separate 7kW battery charge, battery discharge, combined KH7 AC output, and island/EPS limits are modelled.
- A 2kW house plus 7kW battery charge is validated as 9kW total site import when the separately configured site limit permits it.
- Solar plus battery output is capped at 7kW during normal export, high-solar Power Down operation, island operation, and restoration planning.
- Site-import headroom limits only flexible charging rather than incorrectly capping grid bypass at 7kW.
- EPS utilisation and warnings apply only when islanded; grid-connected demand uses site-import diagnostics.
- Last-completed Power Down results persist independently from the live Octopus event entity.
- Observed electricity, gas, import/export, and billing evidence accumulate before commissioning, while actual physical-system value remains commissioning-gated.
- Today, Week, Month, Year, and All-time summaries preserve separate actual and simulated totals and mark incomplete historical days explicitly.
- Mid-day commissioning does not claim pre-installation system value.
- No Python bytecode, `__pycache__`, or pytest cache directories are included.
- 111 shipped files are covered by `FILE_MANIFEST.sha256`.
- Real FoxESS writes remain hard-blocked: backend available, command permission, commissioning, and master control all default to off.
- `pyproject.toml`, the Home Assistant manifest, and runtime constants all identify `0.7.0-alpha3` / `0.7.0a3`.

Black, Ruff, and pre-commit were not available in this isolated build environment. Run the repository's normal Black, Ruff, and pre-commit checks in the Windows development environment before merging the release branch into `main`.
