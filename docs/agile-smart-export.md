# Agile Smart Export — current Alpha7 behaviour

Agile Smart Export is KEMS' export-price-aware strategy for Octopus Agile Outgoing. It compares and plans against real Region L half-hour prices while retaining the same house-demand, battery-reserve, solar and inverter constraints used by the wider KEMS digital twin.

Real FoxESS writes remain blocked during the Alpha7 shadow phase.

## Price collection

KEMS discovers the active Agile Outgoing product and Region L tariff through the public Octopus API rather than hard-coding one product code. Rates retain their real `valid_from`/`valid_to` timestamps and the horizon logic is UK/DST aware.

When a relevant future period is absent, KEMS retries the exact target period and records recovery evidence. It never invents a neighbour price.

## Known prices and incomplete horizons

A missing future price no longer automatically erases the economic plan.

KEMS first keeps the known-price allocation visible and reserves the full maximum discharge capacity of unresolved relevant periods. Bounded partial-horizon dispatch is permitted only when all of the following are true:

- the broad price fetch succeeded;
- every relevant missing slot is positively classified as an upstream Octopus omission/no-result rather than a retrieval failure;
- the current settlement period has a real price;
- enough battery/inverter capacity is reserved for every unknown relevant period;
- no unknown-price period receives an export command.

Any retrieval ambiguity, current-price uncertainty or insufficient reserve restores the full horizon hold.

## Dispatch priorities

Outside cheap import periods:

1. solar serves the house first;
2. battery can serve remaining house demand above the protected reserve;
3. deliberate battery export uses the highest-value eligible Agile periods;
4. unknown future prices reserve opportunity capacity rather than receiving a guessed value.

The current live house-demand basis is the same KEMS live house-load source used by the Live dashboard. The digital-twin slot-average demand is retained separately for replay/parity evidence.

## Solar-aware inverter headroom

The inverter constraint is applied to total AC output, not battery power in isolation.

KEMS calculates current routed solar AC first, then gives the battery only the remaining configured inverter headroom. A deliberate export candidate therefore satisfies:

`solar AC + battery AC <= configured inverter limit`

For the current proposal the configured KH7 limit is 7 kW. The command must not be pre-clipped into a safety pass; independent validation remains authoritative.

## Shadow command and non-zero proof

The optimiser's exact candidate is translated into the inverter-shaped shadow command. Deliberate export requires Feed-in First and grid export enabled; non-export operation remains Self Use.

The independent safety layer checks 13 command invariants including charge/discharge exclusivity, configured charge/discharge/export/inverter limits, minimum SOC and the hardware-write lock.

A genuine non-zero export proof then applies that exact safe candidate to a one-step digital-twin routing replay. It requires:

- optimiser battery export above 0.01 kW;
- command/optimiser parity;
- qualified price horizon (complete or the verified bounded-partial path);
- Feed-in First and export permission;
- 13/13 independent safety;
- strict target/outcome parity within 0.01 kW;
- 100% strict tracking;
- configured discharge/inverter/SOC limits respected;
- hardware writes still blocked.

Alpha7.31 produced genuine repeated non-zero proof passes and is the behavioural baseline for the Alpha7.32 platform cleanup.

## Web and panel

The managed Home Assistant dashboard contains the detailed Agile workspace. KEMS Web Alpha7 adds a read-only Agile page showing the current rate, dispatch mode, live house demand, digital-twin routing, price-horizon qualification, selected export slots, shadow safety and non-zero proof.

Panel4 already includes an Agile Smart Export display mode and therefore does not require a firmware change for Alpha7.32.

## Safety boundary

Agile Smart Export remains a shadow/digital-twin capability until physical FoxESS commissioning verifies the real mappings, sign conventions, site limits and backend. The public `kems.uk` website has no property control path.
