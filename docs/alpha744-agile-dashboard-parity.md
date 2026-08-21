# KEMS 0.7.0-alpha7.44 — Agile dashboard parity and slot decisions

Alpha7.44 is a reporting-focused release for the **Full KEMS Agile** dashboard. It does not change the Agile dispatch policy introduced by Alpha7.40–Alpha7.43 and it does not enable any hardware write path.

## Same-window actual vs simulation

The main daily table now compares **local midnight to the latest retained sample** on both sides. The Agile replay consumes the same household-demand evidence as the actual column, so the comparison no longer reconstructs house demand from grid flows.

This matters during the overnight cheap period: Full KEMS Agile can import a large amount of energy to charge the simulated battery. That grid-to-battery energy is legitimate simulated grid import, but it is not household consumption.

The headline cost row now uses the customer-facing bill basis:

**import cost + standing charge − export income**

Battery-wear assumptions remain visible separately as the **economic outcome** rather than being silently mixed into the headline electricity bill.

## Solar and battery totals

The period aggregator now retains flow evidence already calculated by the Agile replay but previously omitted from aggregated period data:

- simulated house demand;
- solar generation;
- solar to home;
- grid to battery.

The Today table therefore no longer shows `0.0 kWh` simulated solar while the current Agile digital twin is visibly routing solar.

Physical actual solar/battery values remain unavailable when those sources are not commissioned. Alpha7.44 does not convert missing physical telemetry to zero.

## Agile slot decision table

Octopus Agile is a **30-minute settlement tariff**, so the dashboard intentionally shows every half-hour slot rather than merging two potentially different prices into one hourly row.

For every expected local-day settlement period the table shows:

- slot start time;
- published Region L Agile Outgoing price, when available;
- the current KEMS decision.

The decision vocabulary is deliberately compact and operator-facing. It can show, for example:

- `Hold battery / normal solar routing`;
- `Planned battery export 3.500 kWh`;
- `Deadline guard — export …`;
- `Power Down — house first + maximum safe export`;
- `Happy Hour prep — export …`;
- `Happy Hour — maximum safe battery charge`;
- `Cheap period — charge battery / home from grid`;
- `Waiting for Octopus price — capacity reserved`.

Missing Agile prices remain genuinely unknown. The table never invents a price and the existing Alpha7.41 partial-publication planner continues to reserve capacity and replan when later prices appear.

The table is placed below the live graphs and totals so the normal glanceable dashboard remains focused even though all daily slot decisions are available on the page.

## Safety boundary

Alpha7.44 is reporting-only. The established priority order remains:

**Safety / outage → Power Down → Weekend Happy Hour → normal Agile optimisation**

The 10% reserve, physical inverter/export constraints, Alpha7.34 latest-safe-start protection, Alpha7.40 opportunity guard, Alpha7.41 partial-publication behaviour and Alpha7.43 Power Down/Happy Hour rules are unchanged.

**Real FoxESS hardware writes remain blocked.**
