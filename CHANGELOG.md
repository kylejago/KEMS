# Changelog

## 0.2.0-alpha2

- Rebuilt the Observe integration from a clean package layout.
- Moved all runtime core models inside `custom_components/kems/kems_core`.
- Replaced all absolute `kems_core` imports with package-relative imports.
- Added a config flow for selecting Octopus and optional Ohme source entities.
- Added coordinator-backed rate, timestamp, EV, off-peak and Intelligent-slot entities.
- Added regression tests that prevent the original HACS packaging/import failure.
- Added HACS and hassfest GitHub validation workflows.
