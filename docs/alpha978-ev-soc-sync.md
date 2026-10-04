# Alpha9.78 — KEMS-owned EV SOC sync

## Purpose

Replace the external Home Assistant automation that copied the vehicle battery
percentage into Ohme with a first-class, auditable KEMS feature.

## Source and target

KEMS auto-discovers:

- the actual vehicle SOC from the Stellantis Vehicles integration; and
- the Ohme `number.*state_of_charge_input` entity.

Both mappings remain visible through KEMS Reconfigure and diagnostics.

## Explicit opt-in

The write path is disabled by default. A new **KEMS EV SOC sync** switch must be
turned on explicitly after both mappings are present.

The feature is independent of FoxESS Control mode, but KEMS emergency stop blocks
the write. It never starts/stops charging and never changes Ohme charge mode.

## Write contract

KEMS may call only `number.set_value` on the configured Ohme SOC input when:

1. EV SOC sync is explicitly enabled;
2. the EV is connected/plugged in;
3. the actual vehicle SOC is numeric and within 0–100%;
4. the Ohme SOC input is numeric and within 0–100%;
5. source and target differ by at least 0.5 percentage points;
6. KEMS emergency stop is clear; and
7. the 30-second repeated-write cooldown has expired.

Vehicle SOC is state-validity based rather than age-gated because an unchanged
percentage can legitimately retain the same Home Assistant timestamp.

## Event response

The normal KEMS scan still evaluates the sync, but changes to the authoritative
vehicle SOC request an immediate coordinator refresh. Existing Ohme
connection/charging state changes also trigger the established fast KEMS refresh
path, so a newly plugged-in vehicle does not have to wait for the normal polling
interval.

## Diagnostics

The KEMS diagnostic payload includes `ev_soc_sync` with:

- enable state;
- source and target entity IDs;
- connection state;
- actual vehicle SOC;
- current Ohme SOC input;
- immediate readback after a write;
- current status/reason;
- last trigger;
- attempt/success/failure counts;
- last attempt/success timestamps;
- recent audit events; and
- the exact limited write scope.

The source and target entity states also appear in the configured entity/source
state sections.

## Handover from the old automation

After Alpha9.78 is installed:

1. verify both new mappings are auto-discovered;
2. enable **KEMS EV SOC sync**;
3. confirm one diagnostic shows a successful/matched result;
4. disable/delete the old Home Assistant automation to prevent duplicate writes.
