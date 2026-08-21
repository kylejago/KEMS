# Alpha7.47 — promote no-reserve Agile plans

KEMS `0.7.0-alpha7.47` fixes the runtime acceptance failure found immediately after Alpha7.46 installed through the automatic updater on 21 August 2026.

Alpha7.46 correctly built a full provisional export plan across the best currently published Agile prices and correctly reserved `0.0 kWh` for the unpublished 23:00 slot. However, the plan was not promoted into the active shadow plan because the clean-publication-gap wrapper checked a `publication_pending` field that Alpha7.28 recovery evidence does not expose.

## Fix

For a clean publication delay, KEMS now recognises the gap from Alpha7.28's verified recovery evidence and the `octopus_missing_price` recovery outcome, together with a known current settlement slot and a real current Agile price.

When those conditions are satisfied:

- the full known-price provisional allocation is allowed through the existing bounded shadow-dispatch path;
- unpublished-price reserve is restored to `0.0 kWh` immediately after that existing safety path has validated the plan;
- the active rolling plan uses the published-price selected slots rather than leaving them only in `provisional_selected_slots`;
- `dispatch_blocked_for_price_horizon` is cleared by the bounded dispatch path;
- the dashboard can show the known selected export slots and published-price plan coverage;
- an unpublished slot remains blocked from deliberate export until its own price exists;
- when the missing price appears, the normal rolling optimiser reruns and may replace lower-value future export allocations.

Retrieval failures remain conservative. An unknown current settlement price remains a hard block on deliberate current-slot battery export. Existing 10% reserve, house-demand protection, inverter constraints, deadline guard, Power Down priority and Happy Hour priority remain in force.

Real FoxESS hardware writes remain blocked. Alpha7.47 changes shadow/simulation planning only.

## Acceptance check

Before the late 23:00 price is published, a healthy Alpha7.47 runtime should show:

- `Capacity reserved for unpublished slots: 0.0 kWh`;
- the full exportable requirement allocated across published future Agile slots when sufficient physical capacity exists;
- selected known-price rows such as the best late-afternoon/evening periods marked for planned battery export rather than normal hold;
- 23:00 shown as waiting for Octopus price with no capacity reserved;
- 23:30 retained as the scheduled cheap charging period;
- no deadline-forced maximum-discharge cliff while the target remains physically reachable.
