# KEMS pre-installation control lab

KEMS 0.7.0-alpha2 calculates the exact desired behaviour of the proposed KH7 system without sending real inverter commands.

## Modes

- `observe`: monitoring only; no desired commands.
- `simulate`: desired commands are calculated against the virtual KH7 model.
- `shadow`: intended for installation day; real readings are used but commands are not sent.
- `control`: visible in the options flow, but real commands remain hard-blocked in alpha2.

## Virtual scenarios

The KEMS options flow can switch between normal, sunny, cloudy, high-load, active Power Down, daylight outage, night outage, EPS-overload outage, and grid-restoration instability scenarios.

## Whole-house island priority

1. Solar powers the house.
2. Surplus solar charges the battery.
3. Battery supplies only the remaining house shortfall.
4. EV charging and all grid export are disabled.
5. Normal paced-export and Power Down financial behaviour are suspended.
6. The configured island percentage becomes a conservation warning threshold, while the normal battery reserve acts as the emergency floor.

## Safety boundary

The inverter/EPS hardware performs electrical islanding. KEMS only reacts to grid and EPS states. Alpha2 does not write to FoxESS, Octopus, or Ohme.

## Island battery thresholds

The configured island percentage is a conservation threshold, not a hard cut-off. KEMS warns and asks for discretionary load reduction below this level, while whole-house support may continue down to the normal battery reserve, which acts as the emergency hardware floor.
