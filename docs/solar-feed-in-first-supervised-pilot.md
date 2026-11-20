# Original-scope solar Feed-in First — supervised KH7 pilot gate

**Status (20 November 2026): observational design only. No hardware actuation is
authorised by this document, `solar_routing_shadow.py`, or
`solar_routing_pilot.py`.** Live Agile battery Force Discharge and the
15%/10% battery floors already exist separately; do not reimplement them.

## What the installed evidence actually says

The 20 November 22:35 GMT alpha9.242 diagnostic had no PV (night), no surplus,
a large owner-identified electric-shower household load, and a 15% battery SOC.
The solar shadow correctly returned `no_surplus`; this cannot validate an
economic daytime Feed-in First choice.

The same KH7 command binding observed:

- `select.kh7_work_mode` = `Self Use`, status `PASS`;
- `observation_source=command_entity`;
- `readback_entity_id=null` and no candidate independent readback entity.

This is useful as a command-facing observation, **not independent evidence
that a new work mode was applied physically**. Confirm exact KH7 firmware,
Modbus work-mode register/profile and an independent polled register or
otherwise independent electrical response before proposing a live pilot.
Do not guess register numbers from other inverter generations.

## Distinct decision surfaces

1. **Existing physical KEMS Control:** paid battery export, owner-preserved
   Self Use restoration, commissioned 7kW DNO limit, separate 15% deliberate
   export reserve and 10% house-only floor, confirmed off-peak charging and
   Power Down/Happy Hour/EV overrides. Leave this path unchanged.
2. **Existing financial solar shadow:** evaluates only *incremental measured
   PV charging that could be diverted*, vs physically spare future paid
   export capacity and expensive grid import avoidance. It never writes.
3. **New pilot-readiness diagnostic:** checks independent raw-source ages,
   physical PV-to-battery attribution, EV isolation, tariff/event priority,
   a material advantage and KH7 mode/rollback evidence. A candidate is
   *not* approval to change mode. The pilot gate always declares
   `live_mode_switching_enabled=false` and `hardware_writes=forbidden`.

## Acceptance sequence before considering a live writer

- Collect naturally occurring daylight cases with PV above the household
  load, EV unplugged, no Power Down/Happy Hour or cheap import, fresh raw
  FoxESS readings (including SOC), an economically meaningful redirectable
  PV flow and coherent grid-CT/AC-power balance. Record both favourable and
  unfavourable choices over multiple days; avoid falsely counting PV already
  exported as new gain.
- Verify the KH7 *read* path for work mode independently of the select
  command entity. Prove it can distinguish Self Use and Feed-in First at
  the physical register/response level, with separate timestamped readings.
- Independently prove the KEMS-owned pre-change Self Use, MinSOC, Force
  Charge/Discharge and export-limit baseline can be restored and read back.
  If no reliable mode or rollback verification is possible, this issue
  remains read-only.
- In a **separately reviewed and explicitly authorised** supervised physical
  change, use a safe daylight opportunity with no EV charging/event/control
  conflicts. Log before/after work mode, PV, house, battery power/direction,
  grid import/export, inverter AC capacity, charge and discharge headroom,
  rates and SOC; verify physical behaviour, not merely a successful HA
  service response.
- For any eventual live algorithm, mandate state-based rollback on stale or
  inconsistent telemetry, unexpected battery depletion, material day-rate
  import, site DNO/AC headroom violation, event/EV takeover, loss of
  commissioning or command ownership. Apply **at least a 15-minute dwell**
  after changes, hysteresis across Agile half-hour boundaries, a quantified
  economic margin above switch cost, and independent restore confirmation.
  Those limits are design acceptance targets **not active KEMS settings**.
- Require reviewed deterministic tests for mode switch and restoration,
  failure to restore, reboots, HA/Modbus unavailability, EV transitions,
  low-SOC, Power Down and Happy Hour priority, zero/misaligned PV and
  high PV + battery capacity competition before authorising new writes.

## Why the pilot cannot be declared ready today

The current binding only labels the KH7 mode via `command_entity`; no
independent sensor readback or proven solar-mode rollback is available in
the diagnostic. The November evening sample has no PV. These are real,
explicit blockers—not evidence that the already-live paid battery export
doesn't work. The new `pilot_readiness` attribute lists the missing proof
and remains reporting-only.

Tracking: [#365](https://github.com/kylejago/KEMS/issues/365).
