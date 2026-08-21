# Alpha7.49 — reconcile deadline guard with the economic price plan

KEMS `0.7.0-alpha7.49` fixes a Full KEMS Agile planning contradiction exposed by the 21 August 2026 live acceptance data.

Alpha7.48 correctly stopped a 100% simulated battery from accepting impossible solar charge. That made the next discrepancy visible: the dashboard could say the next planned battery-export slot was later, while the live dispatch layer had already escalated into the Alpha7.34 deadline guard and was exporting battery energy immediately.

## Why the two plans disagreed

The rolling economic plan and the deadline guard did not use the same physical-capacity model.

The rolling plan ranked the remaining Agile half-hours by price and treated each slot primarily as available battery-discharge capacity. In the captured case it reported a `15.668 kWh` deadline-capacity margin and therefore selected 16:00 as the next economic export slot.

The Alpha7.34 guard uses a stricter five-minute model of the shared inverter. It gives forecast/proposal solar first use of the AC inverter headroom and only counts the remainder as battery-discharge capacity. At the same instant it calculated:

- required AC battery discharge before cheap power: `48.239 kWh`;
- solar-aware physical capacity remaining to the deadline: `48.571 kWh`;
- only about `0.33 kWh` of genuine physical margin.

The large rolling-plan margin therefore could not safely be used as proof that KEMS was free to wait until 16:00.

## Alpha7.49 rule

Alpha7.49 reconciles the two layers instead of choosing one blindly.

When Alpha7.34 wants to enter `deadline_following`, KEMS now re-evaluates the future price-selected plan with the same solar-aware shared-inverter capacity model used by the deadline guard.

If the selected future plan still has enough physical capacity to reach the configured pre-cheap target, the early deadline escalation is suppressed and the current slot remains price optimised.

If the future selected plan is not physically sufficient, the deadline guard remains active. The required current-slot battery export is then inserted into the economic plan and the same amount of energy is removed from the lowest-value later selected export slot or slots. The total planned battery export therefore does not grow merely because the guard became active.

This produces one internally consistent answer across:

- Decision now;
- the current half-hour row;
- next planned export slot;
- selected price-ranked export rows;
- the deadline guard diagnostics.

## Safety and economics

Alpha7.49 keeps the safety hierarchy unchanged. A physically unreachable target still uses the existing maximum-discharge failsafe, and Power Down / Happy Hour priority is not relaxed by this patch.

The rebalancing rule preserves economics as far as the physical deadline permits: any unavoidable early export replaces the lowest-value later selected energy first rather than adding extra battery export on top of the economic plan.

Real FoxESS hardware writes remain blocked. Alpha7.49 changes simulation/shadow planning and reporting only.
