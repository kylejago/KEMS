# Alpha9.259 evidence recovery and commissioning

The 27 November diagnostic confirms 73 import and 42 export complete
post-commissioning energy days lacking matched prices. Historical charge
evidence must be an actual supplier half-hour observation, not today's rate,
an average or the same KEMS cost being reconciled. Existing
`kems_supplier_charges.json` or `kems_supplier_intervals.json` intake accepts
explicit kind, offset-aware start and end, kwh and charge_pence per half-hour.
Supplier estimates remain separate from billed settlement; standing charges
and event rewards are excluded.

Power Down requires exact contiguous complete baseline rows for the joined
event, matching its dates. Capture both directions independently before
completion. Missing baselines, readings and conflicts remain unresolved.
Never use another event's baseline. Actual awarded Octopoints are separate
settlement evidence.

For gas, compare nonzero overlapping intervals and complete daily totals
against independent lifetime delta evidence. Raw automatic totals remain
quarantined; a zero-only overlap cannot validate units.

EV-only smart charging requires a measured daytime session: charger mode,
EV power, regular off-peak status, site load membership, grid import/export,
PV, battery direction and SOC. Existing candidate routing stays read-only
until KH7 output limiting and physical readback are demonstrated, including
loss of telemetry, EV stop, overload and event transitions. Preserve EV
battery isolation and the 14.5 kW import limit.

FoxESS counters: verify physical register provenance and compare exact
bounded deltas to independent meter readings over matching timestamps.
Do not allocate a larger counter interval to a shorter restart gap.
Recorder: inspect actual persisted reward sensor history or HA Recorder
logs, not just live attribute size.

Legacy parity counts are retained for comparable daytime observations;
inactivity is not parity. No automatic dependency removal, no tariff
authority. Main CI must pass before publication.
