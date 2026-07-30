# Entity inventory

KEMS only creates source-mirror entities when the matching source is configured. Derived entities are always created and may be `unknown` until enough observations exist.

## Observe

Tariff rates and timestamps, off-peak and Intelligent slot status, Ohme charger status-derived EV connection/charging, EV power/SOC, house load, battery SOC/power, solar power, and grid import/export. FoxESS battery power may be derived from battery voltage and current.

## Learn

Learning confidence, typical current-slot house load, typical current-slot solar, predicted energy until the next off-peak period, history sample count, and learning-ready status.

## Advise

Primary advice sensor with explainable recommendation attributes, plus grid-import-outside-cheap-period status.

## Simulate

Observed cost today, simulated KEMS cost today, simulated saving, simulated grid import, simulated battery SOC, simulation-ready status, and whether the simulation shows a saving.
