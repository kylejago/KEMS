# KEMS 0.7.0-alpha7.51 — maximum-discharge plan reconciliation

Alpha7.51 fixes a remaining Full KEMS Agile consistency gap found in the 21 August 2026 Alpha7.50 diagnostics.

## Captured case

At 15:58:42.749 BST the deadline guard had escalated to `maximum_discharge` because the 10% target was physically unreachable under the solar-aware shared-inverter model. Runtime dispatch correctly requested 4.316 kW of battery export, but the rolling price plan still showed the 15:30 half-hour as a hold and kept 16:00 as the next selected export slot.

With roughly 77.25 seconds remaining in the 15:30 slot, 4.316 kW corresponds to about **0.093 kWh** of required current-slot export. That energy must appear in the rolling plan if it is being dispatched.

## Alpha7.51 behaviour

When `maximum_discharge` originates from the deadline guard:

1. Keep the deadline safety decision and export target unchanged.
2. Insert the required current-half-hour export into the rolling selected-slot plan.
3. Reuse Alpha7.49's equal-energy rebalance rule so the same energy is removed from the lowest-value later selected slot.
4. Update `required_in_current_slot_kwh`, `next_export_slot`, the per-slot rolling annotations and deadline-plan evidence together.
5. Do not increase the total planned battery export merely because the current slot became deadline-required.

For the captured 15:30 case, approximately 0.093 kWh is inserted into the current slot. If a later selected slot carried 0.146 kWh at the lowest remaining export value, that later allocation becomes approximately 0.053 kWh, leaving the total planned export unchanged.

This patch does not turn a physically unsafe wait into an economic hold. It only makes the rolling plan describe the deadline decision the runtime is already enforcing.

## Safety boundary

This remains simulation/shadow behaviour. Real FoxESS hardware writes remain blocked unless the separate commissioning and control safety gates explicitly permit them.
