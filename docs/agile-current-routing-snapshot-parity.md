# KEMS 0.7.0-alpha7.30 — Agile current-routing snapshot parity

Alpha7.30 fixes the **Current Agile Smart Export power routing** card without changing the Agile optimiser or command path.

## Problem

Alpha7.29 made **House demand (live)** use the same live KEMS house-load measurement as the Live tab, but the rest of the Agile routing card could still come from the elapsed active-slot accumulator. At a new half-hour boundary that accumulator may not yet contain a complete simulated interval, so several routing fields could show `—`. Other attributes such as the routing slot and legacy `current_action` could also remain from the previous settlement period while the current Agile price had already advanced.

That produced a mixed-time display: a fresh live house value and current price next to stale or unavailable routing evidence.

## Alpha7.30 behaviour

Alpha7.30 builds one **current coordinator routing snapshot** after all earlier Agile patches have published their state.

The snapshot uses:

- the current KEMS scan records and proposal `SimulationEngine` for digital-twin house, solar and routed AC context;
- the exact current Alpha7.28/rolling battery-to-home, battery-export and total-discharge candidate;
- the current Agile settlement slot calculated from the scan timestamp;
- the current rolling `dispatch_action` rather than the pre-Alpha7.28 slot action;
- the same Alpha7.24 outcome-parity accounting idea: preserve the current proposal solar routing and substitute the exact Agile battery candidate before reporting grid/export totals.

The visible routing table therefore reports one coherent set of current values:

- House demand (live)
- Digital-twin house demand
- Solar generation
- Grid import/export
- Solar → home/battery/export
- Grid → battery
- Battery → home/export
- Agile simulated SOC

The previous elapsed-slot routing evidence is retained in `elapsed_slot_average_evidence` for diagnostics, but it no longer drives the primary current-routing table.

## Settlement-slot parity

`routing_slot`, `routing_valid_from`, `routing_valid_to`, `current_agile_rate_pence`, `routing_action`, and `dispatch_mode` are refreshed from the same scan as the power snapshot. This prevents combinations such as a 15:30 Agile rate with a stale 15:00 routing label.

## Safety boundary

Alpha7.30 is reporting-only. It does **not** change:

- Alpha7.28 bounded partial-horizon eligibility or reserved unknown-slot capacity;
- optimiser slot selection or battery export targets;
- the 10% SOC floor;
- 7 kW battery/inverter/export limits;
- Alpha7.25 non-zero proof semantics;
- the independent 13-point shadow command validator;
- hardware commissioning state.

Real FoxESS hardware writes remain blocked.
