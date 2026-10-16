# Alpha9.106 — asynchronous Ohme Unplugged source proof

## Observed live failure
The 16 October 2026 07:42 Alpha9.105 diagnostics show an installed
release but no export: 5.753 kW requested, 0 kW permitted, with Ohme
status and power both unavailable. The Alpha9.105 short grace requires
one same-scan explicit unplugged + 30-second zero-power observation
to arm, which is too restrictive for asynchronous Ohme cloud reports.

## Narrow correction
When Ohme explicitly reports **Unplugged** (connected false and charging
false), paid Agile may arm the memory-only unplugged bridge even when the
Ohme power reading is unavailable or older than 30 seconds.
The explicit status is passed by the normal freshness-aware provider.
Fresh FoxESS house-load and grid-import readings are mandatory.

A connected state, an active charging indication, >0.1 kW charger
power, invalid negative EV power, >0.3 kW grid import, missing or stale
FoxESS meter, or a +1 kW site-load step vetoes the bridge. After losing
the explicit status, no more than 90 seconds of physical corroboration
is allowed without re-arming. No proof persists across restart.

The guard independently checks proof validity on every command cycle.
No source outage alone can grant export without explicit prior unplugged
evidence. This is **not** permission for indefinite all-Ohme unknown.
An independent metered EV circuit would be needed to prove safety
through unbounded charger cloud outages.

## Diagnostics
`data.control_event_refresh.agile_unplugged_source_proof` contains:
assessment, last_confirmed_unplugged_at, outage_started_at,
baseline_house_kw and grace_seconds.

## Unchanged
No change to cheap-period Force Charge, No Paid Export EV MinSOC hold,
Power Down, Happy Hour, household battery reserve, physical energy
evidence, hardware binding, or the 7 kW DNO limit.
