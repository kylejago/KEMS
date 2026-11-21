# KEMS roadmap — live alpha9 priorities (20 November 2026)

**Current installed diagnostic:** `0.9.0-alpha9.239` (commissioned Control,
with established 7 kW/15%/10% physical limits). The historic v0.6/v0.7
roadmap below documents initial development; it is **not today's to-do list**.

1. **Legacy Intelligent cleanup (#498, #449):** the obsolete KEMS Intelligent option, KEMS-owned sensors, dashboard display and WhatsApp trigger were retired in alpha9.240–242. Preserve Ohme-triggered EV protection, and keep #498 open only for supplier daytime-rate clarification and actual post-23:30 charging/restoration acceptance. Do not reintroduce unverified tariff authority.
2. **Complete original price-aware solar-only routing (#365):** the
   read-only candidate currently recommends Self Use versus Feed-in First,
   while live Agile battery Force Discharge already works. Do not duplicate the
   optimiser; require measured benefit, physical command readback, rollback and
   anti-flapping protections before authorising new work-mode writes.
3. **Happy Hour (#349 closed):** normal joined sessions and restoration were accepted on live evidence and the exceptional cases are already regression-tested. New alpha9.248 candidate adds HA coordinator-reload cache invalidation, with no change to event priority or FoxESS commands.
4. **History and meter provenance (#352, #487):** maintain truthful incomplete
   periods and separately labelled estimated credits; never invent kWh or
   supplier awards. Use independent counter evidence before approving backfill.
5. **Performance (#405):** preserve every state-mutating Agile publication,
   safety guard and hardware dispatch; measure multi-morning scan percentiles
   and change only output-equivalent bottlenecks.
6. **UX/documentation:** expose Live KEMS versus No-KEMS clearly, keep the
   underlying what-if engine only when required for verified control planning,
   and archive outdated version-specific operator instructions.

The installation gate remains **06:00–06:30 Europe/London**, with safe-first
deferral during paid export, EV charging or Octoplus events.

---

## Archived v0.6–v0.7 roadmap


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
