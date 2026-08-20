# KEMS 0.7.0-alpha7.43 — Power Down priority and Weekend Happy Hour planning

Alpha7.43 joins two Octopus event types into the Full KEMS Agile receding-horizon planner without weakening the existing battery reserve, inverter/export constraints, price-horizon qualification or hardware-write lock.

## Power Down is an absolute priority

A joined Octopus Power Down takes priority over every normal Agile export price. KEMS never spends the battery energy protected for the joined event simply because an earlier Agile half-hour pays more.

Before a joined Power Down that occurs before the next configured cheap recharge, KEMS protects:

1. the normal 10% battery reserve;
2. forecast household demand to the next cheap period; and
3. additional battery energy to sustain the useful Power Down export target for the full joined session.

The additional Power Down export reserve is deliberately conservative and does not depend on forecast solar arriving. Actual solar during the event is upside rather than a prerequisite for the protected plan.

During the active Power Down, the current Agile price is ignored. Routing priority is:

1. solar to the house;
2. battery to any remaining house demand;
3. remaining safe solar/battery inverter output to grid export;
4. no deliberate EV charging during the active event.

The planner still obeys the configured battery-discharge, inverter, grid-export and minimum-SOC limits.

## Weekend Happy Hour manual source

Octopus currently lets the customer choose a Weekend Happy Hour in Octopus' own interface, while that selected event is not available from the Home Assistant source consumed by KEMS. Alpha7.43 therefore introduces a manual source-neutral event model.

The Full KEMS Agile dashboard exposes:

- **Weekend Happy Hour planning** — enable/cancel the plan;
- **Weekend Happy Hour start** — date and time of the booked slot;
- **Weekend Happy Hour duration** — one or two booked hours.

The planner consumes an event with `source: manual`. A future Octopus/Home Assistant provider can supply the same event shape and replace manual entry without redesigning the optimisation policy.

For the current Octopus scheme KEMS models the published fair-use limit as **16 kWh per selected one-hour Weekend Happy Hour reward**. When two booked one-hour rewards are selected consecutively, planning therefore exposes two reward caps across the two-hour event.

## Preparing battery headroom

KEMS works backwards from the Happy Hour start and calculates the maximum useful battery charge from:

- battery charge power;
- shared inverter power;
- the configured site-import limit when present;
- expected household import during the event;
- the Happy Hour fair-use allowance; and
- available battery capacity.

It then estimates headroom already expected from normal household battery use before the event. If a protected Power Down occurs before the Happy Hour, the expected Power Down discharge also contributes to that future headroom.

If more headroom is required, Full KEMS Agile uses only **known Agile prices** before the Happy Hour and chooses the highest-value eligible half-hours until exactly the required headroom has been created. Unknown or unpublished prices are never guessed. Power Down periods are never consumed for Happy Hour preparation.

While this preparation is in the active planning horizon, ordinary price-led battery export is held back so it cannot create more headroom than the free charging opportunity can use.

## During the Happy Hour

Unless a Power Down overlaps and therefore wins priority, KEMS changes to **Happy Hour charge**:

- solar continues to serve the house first;
- grid import supplies remaining house demand;
- the battery is charged at the maximum safe useful rate;
- deliberate battery discharge is zero;
- deliberate battery export is zero; and
- the fair-use/site-import limits remain visible in the plan.

The Alpha7.43 digital twin corrects the rolling simulated SOC for the free charge so that later Agile decisions can see the replenished battery rather than continuing from the pre-Happy-Hour replay state.

## After the Happy Hour

After the selected event, the normal rolling Agile optimiser resumes from the corrected simulated SOC. The replenished energy can therefore be allocated to the best later known Agile export slots while the existing 10% pre-cheap target and all physical constraints remain in force.

The Happy Hour plan also exposes the best currently known post-event export slot as an operator-facing preview; normal rolling replanning remains authoritative as prices, house demand and solar evidence change.

## Priority order

Alpha7.43 uses this event order:

**Safety / outage → Power Down → Weekend Happy Hour → normal Agile price optimisation**

A Power Down can never be displaced by an Agile price or by Happy Hour preparation. A Power Down that overlaps a Happy Hour also wins the overlap.

## Safety boundary

Alpha7.43 remains simulation/shadow functionality. It adds no direct inverter service call and no FoxESS backend write path. **Real FoxESS hardware writes remain blocked** until the separate commissioning and control boundary is explicitly completed.
