# Alpha7.46 — Agile no-reserve publication planning

KEMS `0.7.0-alpha7.46` changes how Full KEMS Agile treats a clean Octopus publication gap in the current day's export prices.

## Behaviour

When Octopus has successfully returned the current-day tariff but one or more future settlement periods have not yet been published, KEMS now plans the full currently exportable battery energy across the best prices that are actually known. It does **not** reserve battery capacity merely because an unpublished slot might later be valuable.

The common late-day example is the final relevant 23:00–23:30 export slot. The 23:30–00:00 period is already the beginning of KEMS's cheap charging window, so it is not a required discharge slot. If 23:00–23:30 is still unpublished, KEMS allocates the required export across the best published slots instead of holding 3.5 kWh back for an unknown value.

When the missing price appears, the normal rolling optimiser immediately rebuilds the remaining plan. If the newly published slot is better than one or more still-future selected slots, KEMS moves the required remaining export into the better slot and reduces or removes the lower-value future allocations. Energy already exported in elapsed periods is naturally irreversible and the replan starts from the current simulated SOC.

## Safety boundaries

This relaxation applies only to a **clean publication gap**: the broad Octopus price request succeeded and the missing future price is classified as still unpublished. Retrieval failures and ambiguous price evidence keep the existing conservative hold path.

The current settlement period must still have a real published price before KEMS deliberately exports battery energy in it. The 10% target, protected house demand, inverter/export limits, Alpha7.34 latest-safe-start protection, Alpha7.40 opportunity guard, Power Down priority and Happy Hour priority remain unchanged.

Real FoxESS hardware writes remain blocked.

## Dashboard

The battery-plan card now states that unpublished slots have **0.0 kWh reserved**. The half-hour decision table shows `Waiting for Octopus price — no capacity reserved; re-rank when published` for an unpublished future slot. The card also exposes how much of the exportable battery requirement is covered by the currently published-price plan.
