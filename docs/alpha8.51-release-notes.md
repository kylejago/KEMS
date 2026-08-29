# KEMS 0.8.0-alpha8.51

Alpha8.51 is a managed-dashboard presentation-only release that restores a useful half-hour Agile plan table without changing optimiser, routing, settlement, accounting, Power Down, EV policy, FoxESS control, or the hardware-write boundary.

## Half-hour Agile flow table

Today and Tomorrow now render one chronological row per Agile slot with:

- Time
- Price
- estimated end-of-slot SOC
- Grid action and estimated kWh
- Solar action and estimated kWh
- Battery action and estimated kWh

The dashboard consumes the canonical Alpha8.48+ per-slot flow contract directly rather than reconstructing routing from older planner wording.

Compact route labels remain the existing customer-facing vocabulary:

- Grid: `IMPORT`, `EXPORT`, or `IDLE`
- Solar: `HOME`, `BATT`, `EXPORT`, or mixed routes such as `HOME/BATT` and `HOME/EXPO`
- Battery: `HOME`, `EXPORT`, `CHARGE`, or mixed routes such as `HOME/EXPO`

The displayed kWh is the total activity represented by that source/grid column for the slot. For example, solar `HOME/EXPO 2.30 kWh` may consist of 0.50 kWh to home and 1.80 kWh export; with battery `EXPORT 2.10 kWh`, Grid correctly shows `EXPORT 3.90 kWh`.

The active half-hour uses the remaining-slot flow contract. Future rows show the current KEMS plan snapshot and are recalculated continuously.

## Regression boundary

- Existing canonical slot-flow reconciliation remains authoritative.
- No Agile optimiser or dispatch ownership changes.
- No settlement/accounting changes.
- Power Down behaviour is unchanged.
- KEMS Web / Pi / PWA remains `0.8.0-alpha8-web.7`.
- managed ESP32 panel remains `0.8.0-alpha8-panel.1`.
- Real FoxESS hardware writes remain blocked.
