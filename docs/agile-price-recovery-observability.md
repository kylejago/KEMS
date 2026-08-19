# KEMS 0.7.0-alpha7.27 — Agile price recovery observability

Alpha7.27 makes missing Agile Outgoing price recovery directly observable in KEMS diagnostics. Alpha7.26 already retried a missing future settlement slot, but its evidence was only published as Home Assistant entity attributes. A downloaded KEMS diagnostic therefore could not prove whether the retry ran, whether Octopus returned no rate, or whether KEMS encountered a retrieval error.

## Primary fetch and exact half-hour retry

KEMS still performs the normal broad Region L Agile Outgoing fetch first. It then measures the Europe/London settlement-day coverage using the same DST-aware horizon helpers as the planner. For up to four unresolved future slots, KEMS records the exact target interval in both UTC and local time and requests that exact half-hour from the discovered Octopus tariff endpoint.

For every request KEMS records the HTTP status, number of results, number of exact target matches, returned validity intervals, and any error type/message. This evidence is embedded directly in `agile_smart_export.price_fetch_diagnostics`, so it is present in the normal downloadable KEMS diagnostic rather than existing only on a Home Assistant entity.

## Context window recovery

If the exact half-hour request succeeds but does not return the missing target, KEMS performs one small context window request from 30 minutes before the target to 30 minutes after it. This distinguishes two important cases:

- `recovered_context`: the wider request contains the exact target slot, indicating an API filtering/boundary quirk. KEMS can safely recover that exact published rate.
- `octopus_slot_not_published`: Octopus successfully returns neighbouring slots but not the target slot itself. KEMS leaves the target unresolved.
- `octopus_no_results`: Octopus successfully returns no rates in the context window. KEMS leaves the target unresolved.
- `retrieval_error`: KEMS could not complete one of the recovery requests, for example because of an HTTP/client or timeout failure.

The overall recovery state also distinguishes `recovered`, `partially_recovered`, `octopus_missing_price`, `retrieval_error`, and `primary_fetch_error`.

## No invented prices

The context request is diagnostic and recovery-only. KEMS never invents a missing rate and never substitutes a neighbouring price. A recovered rate is accepted only when its `valid_from` and `valid_to` exactly match the unresolved settlement slot.

If Octopus responds successfully but the target slot is still absent, the normal Alpha7.22 price-horizon hold remains active. Alpha7.26 continues to preserve the provisional economic export plan and reserve capacity for the unresolved slot, while executable battery export stays blocked until the existing horizon/deadline safety logic permits it.

## Diagnostic payload

The `agile_smart_export.price_fetch_diagnostics` block includes:

- local settlement date and expected slot count;
- primary fetch success/error information;
- coverage immediately after the primary fetch;
- unresolved labels before targeted recovery;
- each exact half-hour and context window request in UTC and Europe/London time;
- HTTP status and returned result count;
- exact target match count and returned neighbouring intervals;
- per-slot recovery outcome;
- recovered and still-unresolved labels;
- final coverage and an overall recovery interpretation.

`sensor.kems_agile_price_fetch_diagnostics` exposes the same evidence in Home Assistant for live inspection.

## Safety

Alpha7.27 changes price retrieval diagnostics and recovery only. It does not weaken the incomplete-horizon dispatch hold, the 7 kW inverter/export limits, the 10% reserve, Alpha7.25 non-zero proof requirements, or the independent shadow safety validator. Real FoxESS hardware writes remain blocked.
