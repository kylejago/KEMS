# KEMS 0.7.0-alpha7.24 — Agile shadow outcome parity

Alpha7.24 closes the pre-install shadow-routing discrepancy exposed by Alpha7.23.

## Evidence that triggered this change

The first Alpha7.23 live diagnostic correctly passed optimiser-to-command parity and all 13 independent shadow-safety checks, but its digital-twin tracking score was only 50%.

At that instant the rolling Agile dispatch requested about 0.69 kW battery-to-home because the live pre-install snapshot had no physical solar source. The proposal simulation, however, was producing about 3.293 kW of simulated solar against a 0.69 kW house load, so the digital twin correctly routed 0.69 kW solar-to-home, about 2.603 kW solar-to-battery, and 0 kW battery-to-home.

The same Alpha7.23 candidate also counted the full simulated PV power as KH7 AC output even when part of that PV was being routed into the battery on the DC side.

## Alpha7.24 behaviour

Alpha7.24 keeps the Alpha7.23 safety chain intact and makes two targeted corrections.

### 1. Proposal/live solar-aware house headroom

The rolling Agile planner now calculates current house battery headroom from the same `SimulationEngine._simulated_solar_power` path used by the Agile replay, keeping proposal/live solar routing consistent through pre-install shadow and commissioned operation.

That function already chooses live FoxESS PV when it exists and otherwise falls back to the configured proposal-solar model. Pre-install shadow therefore sees the same solar context as the Agile replay, while a commissioned installation naturally uses live PV.

The resulting house battery target remains an optimiser output; Alpha7.24 does not silently clip an unsafe deliberate battery-export request.

### 2. Routed KH7 AC-output normalisation

The Alpha7.23 shadow candidate is still built first. Alpha7.24 then starts from the digital twin's routed KH7 AC output, removes the digital twin's battery-discharge contribution, and substitutes the candidate's exact battery-discharge request.

This means solar routed into the battery is no longer incorrectly counted as inverter AC output. The corrected AC-output value is still passed to the existing independent inverter-limit check.

If the direct routed KH7 value is unavailable, Alpha7.24 falls back to simulated solar minus solar-to-battery plus the candidate battery discharge.

## Outcome parity evidence

Alpha7.24 retains the existing digital-twin target-versus-outcome comparison and adds explicit outcome-parity evidence:

- tracking score
- per-command tolerance result
- outcome parity pass/check state
- routed AC-output basis
- compact persistence in recent Agile shadow decisions
- Control and Agile dashboard visibility

If optimiser parity and independent safety pass but the digital-twin outcome remains outside tolerance, the shadow status becomes `CHECK — shadow outcome mismatch` rather than hiding the discrepancy.

## Safety boundary

Alpha7.24 is still simulation/shadow only:

- no Home Assistant service writes
- no FoxESS write backend
- no real inverter command path
- hardware writes remain blocked
- Alpha7.22 price-horizon hold remains upstream
- Alpha7.23 exact optimiser-command parity and 13-point independent safety validation remain in the chain

## Expected validation of the original Alpha7.23 diagnostic case

With proposal solar around 3.293 kW and house load around 0.69 kW during a price-horizon hold, the corrected shadow should converge on approximately:

- solar to home: 0.69 kW
- solar to battery: 2.603 kW
- battery to home: 0.0 kW
- deliberate battery export: 0.0 kW
- total battery discharge: 0.0 kW
- KH7 AC output: about 0.69 kW
- outcome tracking: 100% if all routed values remain within tolerance

The missing 23:00 price-horizon slot should continue to hold deliberate battery export at 0.0 kW until the horizon becomes complete or an existing legitimate deadline override is required.
