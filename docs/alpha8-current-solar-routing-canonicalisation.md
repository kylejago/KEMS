# Alpha8 current/solar routing canonicalisation

Alpha8 now owns the proven Alpha7.30 current-routing snapshot and Alpha7.31 solar-aware shared-inverter headroom through one non-versioned `agile_routing` boundary.

The canonical runtime owners are exact historical blobs: `agile_current_routing_runtime.py` is byte-for-byte identical to `agile_alpha730_current_routing.py`, and `agile_solar_headroom_runtime.py` is byte-for-byte identical to `agile_alpha731_solar_headroom.py`. The historical files remain frozen regression evidence and no longer appear in the executable compatibility registry.

Alpha7.31 is a coupled layer rather than an independent patch: its frozen runtime imports Alpha7.30 by module name and replaces `_snapshot` plus `_CURRENT_ROUTING_CARD`, while also wrapping Alpha7.17 dispatch, Alpha7.23 shadow construction and the rolling plan. The canonical facade therefore binds the historical Alpha7.30 import name to the canonical byte-identical current-routing module before the unchanged Alpha7.31 runtime is imported.

The same narrow import-name bridge is used for Alpha7.31 itself because the byte-identical Alpha7.34 deadline-guard runtime still imports `_proposal_solar_evidence` through the historical Alpha7.31 module name. The alias points that frozen import to the canonical Alpha7.31 module object; it does not execute the historical file or change the deadline-guard runtime body.

Installation order is preserved: canonical live routing → canonical current routing → canonical solar headroom → canonical deadline guard. Historical loader metadata remains untouched for Alpha7 regression evidence.

This is an ownership migration only. It does not change current settlement-slot selection, proposal replay, battery-candidate substitution, Feed-in First solar routing, shared-inverter headroom, export or discharge clamps, shadow accounting, rolling-plan evidence, deadline calculations, tariff policy, SOC policy, commissioning state, or hardware-write permissions.

Real hardware writes remain blocked behind the existing commissioning and backend gates. No Home Assistant hardware service call, FoxESS provider write, `safe_to_write_hardware`, or `commands_permitted` path is enabled by this slice. No release, tag or version bump is part of this cleanup.
