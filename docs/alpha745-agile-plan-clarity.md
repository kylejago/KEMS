# KEMS 0.7.0-alpha7.45 — Agile battery-plan clarity

Alpha7.45 is a reporting-only follow-up to Alpha7.44. It does not change the Full KEMS Agile optimiser, Power Down priority, Weekend Happy Hour planning, minimum battery reserve, inverter/export constraints, or hardware-write boundary.

## Why the plan can look smaller while prices are still publishing

When one or more future Octopus Agile prices are unpublished, Alpha7.41/Alpha7.28 intentionally separate two quantities:

- **published-price allocations** — energy KEMS can already place into specific known-price settlement periods; and
- **unpublished-slot capacity** — discharge capacity KEMS keeps available for the unresolved slot without inventing a price.

The half-hour table introduced in Alpha7.44 showed the first quantity but only described the second as `capacity reserved`. That could make a correct bounded partial plan look too small.

For example, if 19.8 kWh is already scheduled into known prices and the still-unpublished 23:00–23:30 slot can discharge another 3.5 kWh, the visible selected rows alone do not represent the complete path to the target. The reserved unknown-slot capacity is part of the safety/economic plan even though KEMS will not pretend it knows that slot's price.

## Battery plan card

The Full KEMS Agile dashboard now shows a dedicated **Battery plan to next cheap period** card containing:

- current simulated battery SOC;
- target SOC at the next cheap-period start (normally 10%);
- protected house energy;
- currently exportable battery energy;
- battery export already allocated to published-price slots;
- capacity reserved for unpublished slots;
- the amount still required from those unpublished slots;
- any genuinely unaccounted export requirement;
- projected SOC after only the published-price plan; and
- projected SOC if the reserved unpublished-slot capacity is used.

The target state is reported explicitly as one of:

- covered by the published-price plan;
- covered by published exports plus reserved unpublished-slot capacity; or
- shortfall, with the remaining kWh shown.

This makes it immediately clear whether the current plan can still reach the 10% target without waiting for a late deadline surprise.

## Battery SOC on the operating view

The Live / Actual card now includes physical battery SOC when that source is commissioned. If the physical battery source is unavailable it remains a dash rather than being fabricated.

The Full KEMS Agile Simulation card shows the current simulated battery SOC directly alongside simulated battery power.

## Unpublished settlement rows

For future rows where the Octopus price has not yet been published, the half-hour decision table now shows the amount of discharge capacity being reserved and, where applicable, how much of that capacity is currently required to complete the target plan.

KEMS still never guesses an unpublished Agile price. As soon as Octopus publishes the missing price, the normal rolling optimiser re-ranks the slot and replaces the capacity reservation with a real price-based decision.

## Safety boundary

Alpha7.45 is reporting-only. It does not add inverter service calls or a FoxESS write path. **Real FoxESS hardware writes remain blocked** until the separate commissioning/control boundary is explicitly completed.
