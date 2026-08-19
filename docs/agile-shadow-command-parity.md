# Agile shadow-command parity

KEMS `0.7.0-alpha7.23` adds a read-only bridge between the live Agile Smart Export rolling optimiser and the existing independent shadow-control safety envelope.

The chain is:

`Agile rolling optimiser → hardware-shaped ControlState candidate → 13-point shadow validator → diagnostics/evidence`

No candidate is sent to FoxESS. `real_backend_available` remains false, `commands_permitted` remains false, and every Alpha7.23 Agile shadow entity reports hardware writes as blocked.

## Price-horizon behaviour

Alpha7.23 consumes the final Alpha7.22 rolling dispatch target. If a relevant Agile price is missing and Alpha7.22 has placed the plan into `price_horizon_hold`, the shadow candidate must request exactly `0.000 kW` deliberate battery export. House support may continue.

When the relevant price horizon becomes complete, the candidate copies the current rolling optimiser export, house-support and total-discharge targets exactly. The adapter deliberately does not clip an unsafe optimiser target. The independent validator must see the original request and block it if it violates charge, discharge, export, inverter, SOC, island, import-limit, freshness, or planner-safety rules.

Deadline safety remains visible. If Alpha7.22 activates a valid `deadline_following` or `maximum_discharge` override, Alpha7.23 records that fact while still validating the resulting command envelope independently.

## Evidence

The integration publishes:

- `sensor.kems_agile_shadow_status`
- `sensor.kems_agile_shadow_command`
- `sensor.kems_agile_shadow_safety`
- `sensor.kems_agile_shadow_target_export`
- `sensor.kems_agile_shadow_target_total_discharge`

Changed Agile shadow decisions are retained alongside the existing shadow-validation evidence. Diagnostics include the latest candidate, optimiser parity checks, safety result, digital-twin tracking result, price-horizon state, and recent decisions.

## Alpha7.23 acceptance criteria

A live Home Assistant diagnostic passes this slice when the Agile candidate is available, optimiser parity is true, the 13-point safety result is PASS for a safe command, and hardware writes remain blocked. During an incomplete price horizon, `battery_export_held` must be true and the Agile shadow battery-export target must be exactly `0.0 kW` unless the existing deadline override has legitimately activated.
