# Alpha9.74 — transient EV-hold preservation

## Live defect

The 29–30 September 2026 Alpha9.72 overnight trace proved that the EV MinSOC pre-arm correctly raised FoxESS from the normal 10% baseline to 47% at 23:30 while the EV was connected and idle.

At about 02:07, a temporary FoxESS/source-readiness dropout made the reviewed command/readback entities unavailable. The persisted EV hold itself survived, but the generic backend release path later restored MinSOC to 10% while cheap time was still positively confirmed and the EV remained connected. The 47% hold was only re-applied after commissioning/readiness recovered.

Alpha9.73 separately adds immediate coordinator refreshes for genuine EV and Intelligent-slot transitions. Alpha9.74 retains that behavior and fixes the transient readiness-loss recovery path.

## Alpha9.74 behavior

Alpha9.74 adds a third backend state between apply and release: **freeze**.

Freeze is allowed only when all of the following are true:

- KEMS already owns the FoxESS state;
- the last successfully applied KEMS action was Self Use;
- a persisted EV MinSOC hold exists;
- No Paid Export remains active;
- cheap time is still positively confirmed;
- the EV is not explicitly disconnected;
- KEMS remains in Control mode;
- Master Control remains enabled;
- user commissioning remains acknowledged;
- emergency stop is not active;
- the system is not in island/grid-loss mode.

When those conditions hold but normal write authority is temporarily unavailable, KEMS performs **no FoxESS writes**. It preserves the last successfully applied KEMS-owned Self Use + MinSOC state and reports `freeze_ev_hold` diagnostics.

An active Force Charge is never frozen; loss of safe control authority while charging follows the existing release path rather than leaving a managed charge running unattended.

Once normal telemetry/readiness recovers, the persisted hold is revalidated and normal control reasserts/verifies it on the first usable cycle.

## Explicit release remains authoritative

Freeze is never used when cheap authority is lost, the EV explicitly disconnects, No Paid Export is left, Control/Master/commissioning are disabled, emergency stop is active, or island/grid-loss protection owns the system. Those cases retain the existing restore/release behavior back to the pre-KEMS local mode and MinSOC baseline.

## Hardware scope

Alpha9.74 adds no new hardware command.

It still uses only the already-reviewed Self Use, confirmed-cheap Force Charge and MinSOC-on-grid surface. Freeze itself issues zero writes. Deliberate Force Discharge, direct Ohme commands, import/export power-limit writes, paid/Agile export control and automatic Master enable remain blocked.
