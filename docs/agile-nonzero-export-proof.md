# KEMS 0.7.0-alpha7.25 — Agile non-zero export proof

Alpha7.24 proved that zero-output Agile shadow commands track the proposal/live digital twin correctly. Alpha7.25 adds the next control-readiness proof without enabling real hardware writes.

## Goal

Wait for the live rolling Agile optimiser to select a genuine non-zero battery export target after the complete price horizon is available. Do not force a synthetic export just to satisfy the proof.

When that condition occurs, Alpha7.25 applies the exact optimiser-shaped command to a one-step digital-twin replay. The replay starts from Alpha7.24's routed solar AC contribution, then independently applies battery-discharge, inverter and export limits. The target is not clipped before the existing independent shadow validator sees it.

## Qualification gate

A non-zero proof is only qualified when all of the following are true:

- battery export is greater than 0.01 kW;
- the complete Agile price horizon is available;
- the price-horizon export hold is no longer active.

Until then the proof remains in a WAITING state and the existing Alpha7.24 shadow result remains authoritative.

## Passing proof

A qualified proof requires all checks to pass together:

- the non-zero export still exactly matches the rolling optimiser;
- optimiser-to-command parity passes;
- work mode is Feed-in First and grid export is explicitly allowed;
- the independent shadow safety envelope passes 13/13;
- the candidate-applied digital-twin replay matches charge, battery-to-home, battery export and total discharge within 0.01 kW;
- strict tracking is 100%;
- total battery discharge remains within the configured 7 kW limit;
- KH7 AC output remains within the configured 7 kW inverter limit;
- minimum SOC remains at or above the configured 10% normal reserve;
- real hardware writes remain blocked.

The original Alpha7.24 baseline tracking is retained as `baseline_tracking` and `baseline_outcome_parity` whenever a qualified non-zero replay becomes the active outcome evidence. This makes the transition auditable instead of hiding the fact that the baseline simulation does not itself execute the separate Agile export command.

## Evidence

The status sensor exposes `nonzero_export_proof`, including qualification state, check results, strict tracking and replay output. Recent Agile decisions also retain the proof state, pass/fail flag, strict tracking score and replayed battery export.

The managed dashboard shows the current non-zero proof state, target export, replay export, strict tracking score and the same independent safety command values.

## Safety boundary

Alpha7.25 is still simulation/shadow only. It does not call Home Assistant services, does not expose a FoxESS command backend, and does not permit real hardware writes.
