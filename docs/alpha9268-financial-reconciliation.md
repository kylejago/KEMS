# Alpha9.268 financial reconciliation preparation

## Scope

Supplier estimated charges are compared against complete matching supplier-meter intervals after the commissioning day. Expose dated native and estimated values for all comparable days, not only the last fourteen. The candidate actual-value delta is export delta minus import delta. It is not an extra reward. Preserve native daily records, existing October revaluation audits, standing charges, simulation prices, and reward ledgers.

Do not promote the preview to actual ROI, dashboard or WhatsApp totals until gross-charge treatment of free-hour and EV credits is established, and a single reporting projection has been tested across all consumers. No settlement or physical completeness is inferred. No meter energy, control code or tariff authority changes.

## Historical query guard

After normal current supplier and local CSV intake, stop scheduling Recorder backfill when both uniquely mapped electricity directions have positive complete-day coverage and no complete day lacks valid prices. Existing in-flight results are consumed; a new missing day, conflict or changed scope reopens a bounded search. Live intake and Power Down baseline capture remain independent.

## Remaining acceptance

- Confirm preview totals against local supplier file and full dated audit.
- Confirm no double application of Happy Hour / Intelligent EV-only credits and no counterfactual changes.
- Implement and test one reversible reporting projection across the native period, ROI, canonical bill and WhatsApp consumers; do not silently alter the original ledger.
- Do not retire the legacy observer until dependency checks are complete; no third-party uninstall.
- Do not install a new release before the overnight Alpha9.267 control acceptance.

## Legacy Intelligent dependency review (partial, 2026-11-28)

- `legacy_intelligent_parity_monitor.py` resolves the old integration by registry platform and unique ID, samples daytime agreement only, and keeps bounded transition evidence and retained counters. Missing or stale legacy state is non-authoritative. Its explicit output states that it is not used for tariff or control.
- `ohme_charge_slot_observer.py` owns that monitor and its separate checkpoint store. The parity sample is exception-isolated from the native Ohme service polling; diagnostics expose both. Native Ohme observations must remain available independently of legacy comparison.
- `providers/entity_map.py` and `providers/octopus.py` still accept and read the three deprecated mappings, with freshness checks. `coordinator.py` still includes these mappings in critical refresh subscriptions and in `_ev_hold_source_uncertain`. This is a separate residual dependency, not part of the read-only parity observer. Do not assume deleting configured entities is behaviour-neutral.
- Before retiring mappings or the observer, trace every downstream tariff, EV-hold, notification, diagnostics and configuration consumer, test absent/stale legacy sources and native Ohme-only transitions, and preserve the regular overnight authority. Do not delete saved parity evidence or uninstall the external integration as part of this financial bundle.

The above is a source inspection, not live acceptance or a complete repository-wide reference audit. The Alpha9.267 overnight run and 05:30 handover remain independent release gates; no controller changes are made by this note.
