# Gas and whole-home energy tracking

Gas is part of Observe and Learn so KEMS can report the whole home's energy and cost rather than electricity alone.

## Source priority

KEMS supports these Octopus gas sources:

1. direct daily gas usage and cost totals;
2. a cumulative gas meter in kWh;
3. a cumulative gas meter in m³, converted using the configurable kWh/m³ factor;
4. current gas rate and standing charge for calculated cost when direct cost is unavailable.

The default conversion is 11.1868 kWh/m³ and can be changed in KEMS options.

## Aggregation

- Positive cumulative-meter deltas are retained.
- Negative deltas are treated as meter resets rather than consumption.
- The latest daily total is used for each day.
- Monthly totals are the sum of daily totals or a cumulative-meter delta fallback.
- A typical daily gas value is learned from completed days.

## Whole-home comparison

Observed whole-home cost combines observed electricity net cost, electricity standing charge, gas cost, and gas standing charge when available.

Simulated whole-home cost uses simulated electricity net cost plus the same observed gas cost. KEMS does not claim to optimise gas or heating in this release.
