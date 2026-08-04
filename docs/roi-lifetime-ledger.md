# ROI and lifetime ledger

KEMS 0.5 adds two financial modes and a permanent ledger.

## Pre-install prediction

Before a commissioning date is configured, KEMS uses the accumulated proposal-system simulation value to estimate:

- annual saving
- payback duration and date
- discounted net value over the selected horizon
- confidence based on observed days

The proposal figures remain visible as a benchmark, but KEMS uses the user's actual Intelligent Octopus Go rates and 12p/kWh export assumptions rather than treating the proposal's Flux tariff as live truth.

## Actual ROI

After a commissioning date is set, KEMS compares the real home load's counterfactual import cost with actual import cost and export income. This creates an auditable actual system-value total.

Actual payback deducts:

- the net investment after grants/rebates
- additional installation costs
- daily-accrued maintenance allowance
- manually recorded repair/replacement expenditure

When the recovered amount reaches the investment, KEMS records the first payback date permanently and switches to Profit Mode.

## Permanent ledger

The ledger is stored under `kems.<entry_id>.lifetime`. It is separate from Home Assistant Recorder, so Recorder purges do not remove all-time totals. Simulated value accumulates during the pre-install learning period; real electricity, gas, solar, grid, EV, battery, cost, earnings, avoided-import, and actual-system-value totals begin on the configured commissioning date. It also records best days and operating days.

The existing observation history store remains unchanged and is used to bootstrap the first ledger.
