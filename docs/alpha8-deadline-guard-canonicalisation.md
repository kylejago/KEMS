# Alpha8 deadline-guard canonicalisation

Alpha8 now owns the proven Alpha7.34 latest-safe-start deadline guard through the non-versioned `agile_deadline_guard` boundary.

The canonical runtime owner `agile_deadline_guard_runtime.py` is byte-for-byte identical to the historical `agile_alpha734_deadline_guard.py` implementation. The historical file remains in the repository as frozen regression evidence but no longer appears in the executable Alpha7 compatibility registry.

Installation order is preserved: Alpha7.31 solar/shared-inverter headroom remains the proven base, the canonical deadline guard is installed next, and the canonical cheap-window reporting handover remains outside it.

This slice changes ownership only. It does not rewrite the five-minute solar-aware capacity model, latest-safe-start calculation, ten-minute guard, target-reached handling, deadline-following escalation, maximum-discharge failsafe, house-first routing, shared-inverter/export/max-discharge clamps, or rolling-plan deadline evidence.

The runtime deliberately retains its historical Alpha7.17 dispatch and Alpha7.31 solar-headroom dependencies. Those dependencies belong to the future routing canonicalisation seam and should not be changed as part of this migration.

Real hardware writes remain blocked behind the existing commissioning and backend gates. This canonicalisation does not enable Home Assistant hardware service calls, FoxESS provider writes, `safe_to_write_hardware`, or `commands_permitted`.
