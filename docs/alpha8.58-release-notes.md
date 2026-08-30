# KEMS 0.8.0-alpha8.58

Alpha8.58 restores Octopus Intelligent daytime extra slots behind a fail-closed, multi-signal confirmation gate and makes solar battery-first during every confirmed cheap import period.

## Intelligent extra-slot confirmation

Large daytime import is permitted only when the enabled Intelligent policy is corroborated by the available Octopus and Ohme signals:

- fresh Octopus Intelligent slot is ON;
- both Intelligent start/end timestamps are present and the current time is inside that window;
- Ohme confirms the EV is connected and charging;
- live Ohme charging power is at least 0.5 kW;
- vehicle SOC, when available, is plausible;
- Octopus current or next import rate corroborates the configured cheap rate;
- Octopus current demand, when available, does not contradict the live Ohme charging power.

The field case from 30 Aug 2026 is explicitly locked: Octopus Energy may still report 28.3036p/kWh while the separate Intelligent integration reports the active dispatch. With a 17:33-18:00 Intelligent window, next rate 3.4933p/kWh, Ohme charging at 7.326 kW and site demand 8.682 kW, KEMS must recognise the slot as cheap and use 3.4933p/kWh for simulation/control planning.

Any stale, absent or contradictory primary evidence fails closed to normal day-rate routing. The configured 23:30-05:30 overnight cheap window remains independently authoritative and does not require EV charging.

## Solar during confirmed cheap periods

When a cheap period is confirmed:

1. Grid supplies the house/EV.
2. Solar charges the battery first.
3. Grid supplies only the remaining battery charge request.
4. Combined solar + Grid battery charging stays within the configured battery charge limit and SOC headroom.
5. Solar exports only after battery charge headroom/power is exhausted.

This rule is applied consistently to both the Full KEMS simulation and the Agile Smart Export replay.

## Diagnostics and safety

The snapshot now retains the exact Intelligent-slot confirmation reason and evidence, including the Octopus/Ohme signals and `large_import_permitted` decision, so a field diagnostic can prove why KEMS did or did not authorise the import.

No FoxESS commissioning or hardware writes are enabled. Alpha8.57 house-first routing, Power Down, Happy Hour, export ranking, reserve floors and normal overnight charging remain protected.
