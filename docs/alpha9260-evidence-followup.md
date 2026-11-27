# Alpha9.260 evidence follow-up

The supplier baseline may expose one valid half-hour at a time. Keep each
complete calculation keyed by event, direction and exact UTC half-hour.
Conflicts remain conflicts, including after restart; do not infer a second
half-hour from a partial total. Previously retained complete event totals
remain valid unless contradicted. No ROI or physical-control writes.

Automatic gas remains quarantined. Retain paired provider consumption_kwh
and consumption_m3 values with the same timestamp. Compare ratios and CSV
overlap, but do not infer a calorific conversion from unmatched samples.
Old observations without paired volume may remain incomplete.

Historical charge recovery reads only exact matched Octopus cost entities,
using HA Recorder history with attributes over seven days once per setup,
outside the coordinator's live scan. It cannot recover purged history,
excluded attributes or supplier settlement; the same charge/energy matching
and conflict gates apply. Older data still requires a supplier charge export
or verified tariff history with exact tariff/product and effective dates.
No today's-rate substitution or automatic historic ledger adjustment.

EV-only routing readiness uses existing retained trace samples outside
confirmed cheap periods. This is not proof of a Smart Charge discount or
independent circuit isolation. Do not issue new KH7 power commands without
time-aligned load scope, power balance, output-limiting readback and failure
transition evidence. Retain the existing shared-bus MinSOC hold.

Rolling plan timing separates physical budget and slot allocation as nested
subphases of the existing rolling plan timing; do not add nested times to
the parent total. No change to dispatch calculations or cadence. Legacy
compatibility layers remain required by existing module identity contracts;
do not remove them merely because of their historical names.
