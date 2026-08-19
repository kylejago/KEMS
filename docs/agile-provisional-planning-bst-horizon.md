# KEMS 0.7.0-alpha7.26 — Agile provisional planning & BST horizon

Alpha7.26 separates **economic planning** from **dispatch permission** when the rolling Agile price horizon is incomplete.

## Why this release exists

Alpha7.22 deliberately blocked battery export whenever a relevant future Agile price was unknown. That safety behaviour was correct, but the hold implementation also cleared the rolling selected slots and replaced every remaining planned export with zero. The dashboard therefore showed only `hold`, even when KEMS knew it had substantial exportable battery energy and already knew most of the day's prices.

Alpha7.25 then depended on a genuine non-zero optimiser target with a complete horizon, so an incomplete final price slot prevented the new proof from ever becoming eligible.

The 19 August 2026 diagnostic also showed a repeatable UK summer-time boundary pattern: the final local-day prices at 23:00 and 23:30 BST were missing from the retained Agile price set. Alpha7.26 does not invent those rates. Instead it adds an exact-slot retry and explicit fetch diagnostics so KEMS can distinguish a broad-fetch gap from a price that remains unavailable upstream.

## Provisional economic plan

When the price horizon is incomplete, Alpha7.26 first preserves the rolling optimiser's economic allocation before Alpha7.22 applies the dispatch hold.

The live dispatch path remains conservative:

- current deliberate battery-export target remains **0 kW**;
- `price_horizon_hold` remains active;
- the existing deadline override remains authoritative;
- Alpha7.25 cannot qualify its non-zero proof while the horizon hold is active;
- real FoxESS hardware writes remain blocked.

Separately, KEMS now publishes a provisional economic plan showing where it would allocate export using every price that is currently known.

## Capacity reserved for unresolved slots

A missing price must not be treated as either free energy or a known bad slot.

For each unresolved half-hour before the 23:30 cheap-window deadline, Alpha7.26 calculates the maximum discharge capacity that could still fit in that slot. That capacity is reserved from the provisional known-price allocation by trimming the lowest-priced selected known slots first.

This keeps the highest known-value export slots visible while leaving room for an unresolved late slot to become attractive when its price arrives.

The reserve is planning evidence only. It does not permit dispatch into an unpriced slot.

## Dual SOC projection

The Agile SOC trajectory now exposes both outcomes:

1. **Safety-hold projection** — what happens if KEMS continues to execute the current zero-export hold.
2. **Provisional economic projection** — what the battery trajectory would look like if the known-price economic plan executes and the reserved unresolved-slot capacity is later used before the deadline.

The executable projection remains the safety-hold path until the horizon becomes complete or the existing deadline safety override takes control.

Future solar is still not pre-spent. Every normal KEMS coordinator scan recalculates the plan using the latest simulated/live solar and SOC evidence.

## BST/local-day price retry

After the normal broad Agile rate fetch, Alpha7.26 measures the current Europe/London local day against the DST-aware 46/48/50-slot settlement calendar.

For up to four still-missing future slots, KEMS performs a targeted request for that exact `valid_from` → `valid_to` half-hour. It then records:

- local date;
- expected slot count;
- known count after the primary fetch;
- missing labels after the primary fetch;
- exact slots retried;
- slots recovered by the targeted retry;
- any retry error;
- known count after targeted retry;
- unresolved missing labels.

No rate is synthesized. If Octopus still does not return the price, the slot remains unresolved and the normal export safety hold remains active.

## New evidence

Alpha7.26 adds:

- `sensor.kems_agile_provisional_export_plan`
- `sensor.kems_agile_price_fetch_diagnostics`
- provisional export fields on upcoming Agile audit rows
- hold-vs-provisional deadline SOC attributes on `sensor.kems_agile_soc_trajectory`
- dashboard presentation that separates **Economic plan** from **Dispatch**.

Expected incomplete-horizon behaviour is therefore no longer a table of meaningless zero plans. KEMS should show the best currently-known export allocation, the capacity reserved for unresolved prices, and a separate dispatch column stating that export is still blocked.

## Safety boundary

Alpha7.26 remains simulation/shadow only. It adds no FoxESS command backend, calls no Home Assistant service to control an inverter, and never permits real hardware writes.
