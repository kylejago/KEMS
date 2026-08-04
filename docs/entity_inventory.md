# Entity inventory — v0.6.0-beta1

KEMS creates source-mirror entities only when the matching source is configured. Derived analysis and proposal-simulation entities are created automatically and may be `unknown` until enough observations exist.

## Observe — electricity and tariff

- current and next Intelligent Octopus Go import rates
- optional observed export rate plus fixed 12p/kWh simulation export rate
- normal off-peak and Intelligent slot status
- confirmed-cheap status
- electricity standing charge
- next off-peak start and off-peak end

## Observe — live power and EV

- house load
- solar power
- non-negative grid import and export magnitudes
- signed net grid power, grid direction, raw source readings, and the normalisation mode
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
- paced battery export target, exportable energy, home reserve, hours to cheap period, and projected SOC
- home-reserve forecast source, projected pre-cheap grid import, and export-paused status

## Simulate — Octoplus Power Down

- joined and active session status
- session start, end, duration, Octopoints rate, and p/kWh bonus rate
- net import-minus-export baseline and baseline completeness
- battery reserve and pre-session export-reduction status
- session export power target and estimated exported energy
- estimated rewardable reduction, Octopoints bonus, fixed 12p export income, and total income
- simulated Power Down bonus accumulated today

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

## ROI and lifetime ledger

- `sensor.kems_roi_status`
- `sensor.kems_system_investment`
- `sensor.kems_predicted_annual_saving`
- `sensor.kems_predicted_payback_years`
- `sensor.kems_predicted_payback_date`
- `sensor.kems_predicted_net_value`
- `sensor.kems_actual_value_created_today`
- `sensor.kems_actual_value_created_total`
- `sensor.kems_actual_roi_percentage`
- `sensor.kems_actual_payback_remaining`
- `sensor.kems_actual_payback_date`
- `sensor.kems_actual_net_profit`
- `binary_sensor.kems_roi_ready`
- `binary_sensor.kems_system_installed`
- `binary_sensor.kems_system_paid_back`
- lifetime electricity, gas, solar, grid, EV, battery, cost, earnings, system-value, and operating-day sensors
