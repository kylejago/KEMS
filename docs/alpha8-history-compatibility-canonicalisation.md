# Alpha8 history-compatibility canonicalisation

This slice is an **ownership migration only**. It moves the proven Alpha7.15
Home Assistant Energy-history schema compatibility and sensor-backed historical
backfill diagnostics behind a non-versioned Alpha8 boundary without changing its
runtime body.

## Baseline

The branch starts from exact `main`:

- commit `6cc09530b27c4de7781be9b346bb62cd327dce72`
- tree `5c6e10c29569023e9a072be3113b4e19e5057079`

## Byte-parity boundary

The canonical runtime file reuses the historical Alpha7.15 Git blob exactly:

- history compatibility: `2a2d1a6afdbf5860b90c28bdab7da209391827c9`

`agile_history_compatibility_runtime.py` points at that exact blob. No runtime body is rewritten. The historical `agile_alpha715_backfill.py` file remains in the tree as regression evidence and the historical Alpha7 compatibility-order metadata remains unchanged.

## Installation boundary

Alpha7.15 historically installs in `PRE_BASE_PATCHES` immediately after
`agile_history_backfill_v2`. That order is retained because the layer wraps the
enhanced Energy-source parser and the shared `AgileHistoryBackfill` class before
`agile_smart_export_runtime_base` is imported.

No frozen downstream runtime imports `agile_alpha715_backfill` by module name or
requires that historical module object. Later pre-install evidence consumes the
shared `agile_history_backfill` behavior. The canonical facade therefore delegates
directly to the byte-identical runtime and requires no `sys.modules` legacy-name
bridge.

## Preserved behavior

The migration keeps the exact Alpha7.15 contract:

- both current and legacy Home Assistant Energy grid schemas remain accepted;
- enhanced backfill source discovery remains the wrapped parser;
- backfill method, reason and direct-source diagnostics remain visible entities;
- grid import/export, solar, battery charge/discharge and battery-SOC diagnostics
  remain published;
- diagnostic entities remain removed during backfill shutdown; and
- historical reconstruction remains observational evidence only.

## Deliberately excluded

Alpha7.14–7.17 dashboard ownership and Alpha7.17 dispatch ownership are not moved
in this slice. In particular, Alpha7.15 dashboard still imports the historical
Alpha7.14 dashboard constant and will be migrated with that dependency boundary
separately.

## Safety

This layer reads and publishes historical evidence; it does not issue Home
Assistant hardware service calls or FoxESS provider writes. It cannot set
`commands_permitted=True` or `safe_to_write_hardware=True`; real hardware writes remain blocked and commissioning is not bypassed.

The manifest remains `0.8.0-alpha8.0`; there is no release, tag or version bump.
