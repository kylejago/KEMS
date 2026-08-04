# Roadmap

## 0.6.0-beta1 — stable read-only baseline

- Observe, Learn, Advise, and Simulate
- KH7 7kW paced export and home reserve
- fixed 12p export and Power Down planning
- ROI/lifetime accounting and corrected dashboards
- main-branch rollback point

## 0.7.0-alpha2 — validated scenario fixes

- Power Down EV blocking
- Island conservation threshold separated from emergency floor
- Low-SOC outage runtime correction
- Explicit virtual scenario input diagnostics
- Safer Control Lab dashboard controls

## 0.7.0-alpha1 — pre-installation Control Lab

- hardware-independent command planning
- Observe / Simulate / Shadow / blocked Control modes
- virtual normal, solar, cloud, high-load, Power Down, outage, EPS-overload, and unstable-grid scenarios
- whole-house island solar-first routing
- stale-data, emergency-stop, EPS, reserve, and grid-restoration safeguards
- interactive Home Assistant lab controls
- no real hardware writes

## Next control alphas

- discover commissioned KH7 read/control capabilities
- map supported FoxESS work-mode, SOC, charge-period, and export-limit controls
- add a verified command audit log and per-command read-back
- add grid/EPS source discovery from the installed inverter
- replay longer recorded load/solar days in accelerated tests

## Installation day — 17 August 2026

- verify Modbus readings, units, signs, DNO/EPS limits, and grid/island state
- run real readings in Shadow mode
- enable one command family at a time after read-back verification
- perform a controlled whole-house outage test with the installer

## Stable 0.7 release

Only after one successful overnight charge, daytime self-use/export cycle, grid restoration, safety-stop test, and preferably a real Power Down session.
