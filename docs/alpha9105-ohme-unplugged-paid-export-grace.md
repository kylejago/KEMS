# Alpha9.105 — bounded verified-unplugged Ohme outage continuity

## Live defect

The Alpha9.104 16 October 2026 06:30 diagnostic shows a 5.177 kW
paid Agile export request capped to 0 kW even though FoxESS power
telemetry and battery reserves are healthy. Ohme status and charger
power had concurrently turned `unavailable`. Earlier unplugged grace
logic requires a fresh Ohme power sample in the final command guard,
so that grace cannot operate during a simultaneous status/power dropout.

## Narrow fix

- A fresh confirmed **unplugged** status *and* a fresh zero-power
  Ohme observation establish a memory-only anchor. No anchor survives
  a KEMS restart.
- A short outage can inherit that proof only for up to 90 seconds
  from its first observed missing reading; it must also begin within
  90 seconds of the last fresh unplugged observation.
- Fresh independent FoxESS house-load and grid-import values must
  remain within the previously observed house load + 1 kW and
  <=0.3 kW grid import, respectively. Stale or missing readings block.
- A connected car, a charging state, any measured positive (>0.1 kW)
  or invalid negative EV power, meter spike, outage expiry or lost
  coordinator proof immediately restores the default fail-closed gate.
- The *final* paid Agile physical command guard independently checks
  that the same bounded proof still holds. An evidence string alone
  cannot grant export.

This handles recurring brief cloud outages but intentionally does
**not** allow indefinite exporting through extended unknown charger
status. Independent metering of the EV circuit would be required to
prove EV zero-load during unbounded outages.

## Unchanged

Only the paid Agile physical export evidence path is affected. No
changes to EV MinSOC hold, No Paid Export policy, confirmed cheap
Force Charge, Power Down or Happy Hour authority, source freshness,
FoxESS limits, physical battery reserve, or the 7 kW DNO ceiling.
