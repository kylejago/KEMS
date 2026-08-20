# KEMS 0.7.0-alpha7.42 — focused Full KEMS Agile dashboard

Alpha7.42 turns the **Full KEMS Agile** tab into an operator view rather than a diagnostics dump.

## What the page shows

The top of the tab now answers the four things that matter while watching KEMS operate:

- what KEMS is doing now;
- the current Agile export price;
- whether tomorrow's prices are complete or still publishing;
- the next planned export slot.

A live/actual column sits beside the current Full KEMS Agile digital-twin column, using the same five power concepts: house load, solar generation, battery net power, grid import and grid export.

Two separate 24-hour graphs make the comparison readable:

1. **Actual power — last 24 hours**
2. **Full KEMS Agile simulated power — last 24 hours**

The simulated battery series uses one signed convention: **positive = discharge, negative = charge**.

## Daily and longer-period totals

The tab includes a compact **Today totals — actual vs Full KEMS Agile** table covering:

- house energy;
- solar generation;
- grid import;
- grid export;
- battery charged;
- battery discharged;
- export income;
- net electricity cost.

It also includes a small period-cost table for today, 7 days, 30 days and all tracked time.

## Missing live hardware data

Alpha7.42 deliberately does not turn missing physical data into zero. The recorder-friendly live graph entities are always present, but a source remains `unavailable` until KEMS has a real reading. This is particularly important before FoxESS battery, solar and export telemetry is commissioned.

For the same reason, the live daily solar/battery totals are `—` when there is no trustworthy physical source for those intervals.

## Diagnostics are not deleted

The detailed Agile price-slot, validation, shadow and control evidence still exists in KEMS state/diagnostics. Alpha7.42 only removes that density from the primary Full KEMS Agile dashboard tab.

## Safety boundary

This release is reporting-only. It does not alter:

- the 10% battery reserve;
- Alpha7.34 latest-safe-start protection;
- Alpha7.40 economic opportunity protection;
- Alpha7.41 progressive price publication handling;
- inverter, charge, discharge or export limits;
- the shadow/control safety gates.

Real FoxESS hardware writes remain blocked.
