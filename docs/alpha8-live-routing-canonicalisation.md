# Alpha8 live-routing canonicalisation

Alpha8 now owns the proven Alpha7.29 live house-demand reporting parity through the non-versioned `agile_live_routing` boundary.

The canonical runtime owner `agile_live_routing_runtime.py` is byte-for-byte identical to the historical `agile_alpha729_live_routing.py` implementation. The historical file remains in the repository as frozen regression evidence but no longer appears in the executable Alpha7 compatibility registry.

Installation order is preserved: the historical Alpha7.28 bounded-partial horizon patch remains immediately before the canonical live-routing boundary, and the historical Alpha7.30 current-routing snapshot remains immediately after it.

This slice changes ownership only. It does not rewrite the `sensor.kems_house_load` source, simulated house-load evidence, live/simulated difference reporting, dashboard labels, fallback behaviour, runtime manager publication chain, or dashboard installation chain. Alpha7.29 remains reporting-only and cannot change rolling optimisation, dispatch targets, safety validation, SOC policy, price-horizon policy, or hardware-write permissions.

Alpha7.30 and Alpha7.31 are deliberately not migrated in this slice. Alpha7.31 directly patches the Alpha7.30 module namespace (`_snapshot` and `_CURRENT_ROUTING_CARD`) while also wrapping Alpha7.17 dispatch, Alpha7.23 shadow construction, and the rolling plan. Moving either side of that pair independently would change the object being patched rather than merely changing ownership. Their canonicalisation therefore remains a separate coupled-routing seam.

Real hardware writes remain blocked behind the existing commissioning and backend gates. This canonicalisation does not enable Home Assistant hardware service calls, FoxESS provider writes, `safe_to_write_hardware`, or `commands_permitted`.
