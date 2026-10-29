# Alpha9.159 emergency startup fix

## Evidence
29 October 2026 20:43 HA log: `agile_flow_presentation.py:653` called an async base settlement without awaiting it, and KEMS initialisation subsequently failed with `dict object can't be awaited`. Alpha9.158 only converted the base and coordinator while six inherited overrides were synchronous.

## Immediate safe correction
Restore unchanged Alpha9.157 source for `agile_current_day_settlement.py`, `agile_settled_soc_handoff.py` and `coordinator.py` together, with matching synchronous unit tests. The promised Alpha9.158 off-event-loop Tomorrow optimisation is **temporarily reverted** pending comprehensive integration and MRO tests. This correction does not optimise runtime wall time; it restores operability.

A dedicated regression test checks all six synchronous override signatures, the synchronous Tomorrow handoff, and both coordinator settlement call sites.

## Safety unchanged
Preserve FoxESS and EV hardware permissions, 7 kW DNO export cap, 15% planning SOC target, 10% hard floor, commissioning, Ohme hold, Power Down, Happy Hour, tariff routing and safe-first 06:00–06:30 no-export updater. Do not force-install mid-export. Requires the normal Home Assistant restart after install.
