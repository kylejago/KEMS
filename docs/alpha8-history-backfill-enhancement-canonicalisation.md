# Alpha8 enhanced history-backfill canonicalisation

This is an **ownership migration only** for the enhanced historical-backfill layer currently retained as `agile_history_backfill_v2.py`.

## Boundary

The live PRE_BASE compatibility chain keeps the same execution order:

1. Agile reporting refinements
2. hard deadline dispatch
3. enhanced historical backfill
4. Alpha7.15 Energy-schema compatibility
5. import `agile_smart_export_runtime_base`

The enhanced backfill runtime is moved behind the canonical `agile_history_backfill_enhancement` owner. Its runtime file reuses the exact historical Git blob:

`58a4f238f499faa916e91c39760f71839a066c7f`

No runtime body is rewritten.

## Why a legacy-name bridge is required

The frozen, byte-identical Alpha7.15 compatibility runtime still imports:

`from . import agile_history_backfill_v2 as enhanced`

and then patches `enhanced._energy_sources` in place. The canonical facade therefore binds the historical `agile_history_backfill_v2` import name to the canonical byte-identical runtime object before the Alpha7.15 compatibility installer runs. This preserves one shared module identity and the proven PRE_BASE patch sequence.

## Preserved behavior

The runtime continues to:

- prefer configured direct power long-term statistics when usable;
- publish transparent source diagnostics;
- fall back to Home Assistant Energy dashboard cumulative counters when direct statistics cannot recover older days;
- query Recorder only through read-only `get_statistics` calls;
- reconstruct hourly grid import/export, solar, battery and derived house-demand evidence;
- require the existing historical-day coverage threshold before accepting a recovered day.

The Recorder service calls are historical-data reads, not hardware control calls.

## Explicit non-goals

`agile_smart_export_reporting` and `agile_deadline_dispatch` remain untouched. They are already functional, non-versioned owners and do not need renaming merely for consistency.

This change does not alter tariff logic, dispatch, SOC policy, charging/export limits, commissioning, provider behavior, or Home Assistant hardware control. It introduces no FoxESS write path and cannot enable `safe_to_write_hardware` or `commands_permitted`.

KEMS remains `0.8.0-alpha8.0`; no release, tag or version bump is part of this cleanup.

**Real hardware writes remain blocked.**
