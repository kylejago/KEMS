# KEMS 0.7.0-alpha7.28 — bounded partial-horizon dispatch

Alpha7.28 changes how KEMS treats a missing Agile Outgoing settlement price after Alpha7.27 has proved that the gap is upstream.

## Why

Alpha7.27 demonstrated the 19 August 2026 case clearly: Octopus returned HTTP 200 for the exact 23:00 BST settlement request but returned no target record. A wider context request returned the neighbouring 22:30 BST interval while still omitting 23:00. KEMS therefore classified the price as `octopus_missing_price` rather than a retrieval failure.

The previous all-or-nothing horizon policy then became unnecessarily conservative. Alpha7.26 had already produced a known-price economic plan and reserved the maximum discharge capacity of the unresolved slot, but Alpha7.22 still forced every deliberate battery-export target to zero.

## Bounded partial-horizon rule

Alpha7.28 permits known-price dispatch only when every condition below is true:

- Alpha7.22 would otherwise be holding battery export because the relevant horizon is incomplete.
- Alpha7.26 has a provisional known-price plan.
- the current settlement slot has a real Agile price.
- Alpha7.27's primary price fetch succeeded.
- Alpha7.27 classified the unresolved relevant slot as `octopus_missing_price`.
- every relevant targeted retry ended as `octopus_slot_not_published` or `octopus_no_results` rather than a retrieval error.
- every unresolved relevant label still matches Alpha7.27's unresolved evidence.
- the full maximum discharge capacity of every unresolved relevant slot is reserved.

If any one of those checks fails, the original full price-horizon hold remains unchanged.

## Dispatch behaviour

The Alpha7.26 provisional selected slots become the bounded executable allocation. The current slot is passed back through the existing Alpha7.17 dispatch calculator, so house demand keeps first priority and battery export remains constrained by the configured battery, inverter and export limits.

An unresolved slot is never given an estimated or neighbouring price. It is never selected for price-optimised dispatch while unresolved. Its maximum discharge capacity remains reserved for a later replan if Octopus subsequently publishes the missing rate.

## Non-zero proof

Alpha7.25's original complete-horizon proof remains unchanged in its own module. Alpha7.28 adds one narrowly qualified alternate proof basis: `bounded_partial_horizon`.

A non-zero target on that basis still requires:

- optimiser-to-command parity;
- Feed-in First and explicit grid-export permission;
- 13/13 independent shadow safety;
- strict 0.01 kW candidate-applied target/outcome parity at 100%;
- configured discharge and inverter limits;
- minimum SOC at or above the normal 10% reserve;
- verified upstream missing-price evidence;
- a known current price;
- full unresolved-slot capacity reservation; and
- unresolved-slot dispatch remaining blocked.

## Safety boundary

This release remains simulation/shadow only. It does not add a FoxESS control backend, does not call Home Assistant services to command an inverter, and does not enable real hardware commands. Real FoxESS hardware writes remain blocked.
