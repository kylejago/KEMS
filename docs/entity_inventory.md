# Entity inventory — v0.4.0-alpha1

KEMS creates source-mirror entities only when the matching source is configured. Derived analysis and proposal-simulation entities are created automatically and may be `unknown` until enough observations exist.

## Observe — electricity and tariff

- current and next Intelligent Octopus Go import rates
- live or fallback export rate
- normal off-peak and Intelligent slot status
- confirmed-cheap status
- electricity standing charge
- next off-peak start and off-peak end

## Observe — live power and EV

- house load
- solar power
- grid import, export, and signed net grid power
- battery SOC and power
- EV connected, charging, power, and last reported SOC

## Observe and Learn — gas

- gas current rate and standing charge
- gas use and cost today
- gas use and cost this month
- typical daily gas use
- gas-data availability and coverage attributes

## Learn and Advise

- history sample count
- data quality
- learning confidence and readiness
- typical current-slot house load and solar
- predicted energy until off-peak
- explainable advice with priority/confidence attributes
- grid import outside cheap periods

## Simulate — current power flow

- simulated house load
- simulated proposal/live solar power
- simulated grid import, export, and signed net grid power
- simulated battery power and SOC
- proposal-solar-active and battery-export-enabled statuses

## Simulate — daily totals

- observed electricity net cost
- simulated electricity net cost and saving
- observed and simulated grid import/export
- observed and simulated export income
- simulated solar generation and curtailment
- simulated battery charged, delivered to home, and exported
- avoided day-rate grid import

## Whole-home totals

- observed whole-home electricity-plus-gas cost
- simulated whole-home cost
- whole-home simulated saving
- total whole-home energy
- gas share of whole-home energy

## System diagnostics

- KEMS status and phase
- system profile and array attributes
- simulation export rate and full simulation attributes
- data quality, learning coverage, and history samples
