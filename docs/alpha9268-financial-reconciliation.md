# Alpha9.268 financial reconciliation preparation

## Scope

Supplier estimated charges are compared against complete matching supplier-meter intervals after the commissioning day. Expose dated native and estimated values for all comparable days, not only the last fourteen. The candidate actual-value delta is export delta minus import delta. It is not an extra reward. Preserve native daily records, existing October revaluation audits, standing charges, simulation prices, and reward ledgers.

Do not promote the preview to actual ROI, dashboard or WhatsApp totals until gross-charge treatment of free-hour and EV credits is established, and a single reporting projection has been tested across all consumers. No settlement or physical completeness is inferred. No meter energy, control code or tariff authority changes.

## Historical query guard

After normal current supplier and local CSV intake, stop scheduling Recorder backfill when both uniquely mapped electricity directions have positive complete-day coverage and no complete day lacks valid prices. Existing in-flight results are consumed; a new missing day, conflict or changed scope reopens a bounded search. Live intake and Power Down baseline capture remain independent.

## Remaining acceptance

- Confirm automatic preview totals against retained matched meter and price evidence; optional historical CSVs can corroborate but are not a recurring requirement.
- Confirm no double application of Happy Hour / Intelligent EV-only credits and no counterfactual changes.
- Implement and test one reversible reporting projection across the native period, ROI, canonical bill and WhatsApp consumers; do not silently alter the original ledger.
- Archive-only legacy comparison polling is retired; preserve checkpoint and native Ohme polling. Do not remove residual configured control mappings or uninstall the third-party integration.
- Do not install a new release before the overnight Alpha9.267 control acceptance.

## Legacy Intelligent dependency review (partial, 2026-11-28)

- `legacy_intelligent_parity_monitor.py` resolves the old integration by registry platform and unique ID, samples daytime agreement only, and keeps bounded transition evidence and retained counters. Missing or stale legacy state is non-authoritative. Its explicit output states that it is not used for tariff or control.
- `ohme_charge_slot_observer.py` owns that monitor and its separate checkpoint store. The parity sample is exception-isolated from the native Ohme service polling; diagnostics expose both. Native Ohme observations must remain available independently of legacy comparison.
- `providers/entity_map.py` and `providers/octopus.py` still accept and read the three deprecated mappings, with freshness checks. `coordinator.py` still includes these mappings in critical refresh subscriptions and in `_ev_hold_source_uncertain`. This is a separate residual dependency, not part of the read-only parity observer. Do not assume deleting configured entities is behaviour-neutral.
- Before retiring mappings or the observer, trace every downstream tariff, EV-hold, notification, diagnostics and configuration consumer, test absent/stale legacy sources and native Ohme-only transitions, and preserve the regular overnight authority. Do not delete saved parity evidence or uninstall the external integration as part of this financial bundle.

The above is a source inspection, not live acceptance or a complete repository-wide reference audit. The Alpha9.267 overnight run and 05:30 handover remain independent release gates; no controller changes are made by this note.

## Charge provenance and reward review

The dated audit distinguishes selected Octopus CSV charge intervals from integration-calculated estimates. A complete day of prices is not necessarily a day of verified supplier billing. The full known Happy Hour date set is retained independently of the itemised reward audit display limit, including booked hours awaiting credit evidence. Missing event history does not establish absence of rewards.

Octopus documents Happy Hour as a normal usage charge followed by a separate account refund: https://octopus.energy/help-and-faqs/articles/when-do-i-get-weekend-happy-hour-refund/ . The upstream Home Assistant Octopus Energy integration documents that it cannot reliably adjust costs for extra Intelligent dispatches when planned dispatch data is unavailable, including Ohme: https://bottlecapdave.github.io/HomeAssistant-OctopusEnergy/faq/ and https://bottlecapdave.github.io/HomeAssistant-OctopusEnergy/entities/electricity/ . Therefore integration-only estimated import charges must not automatically replace native amounts. A CSV-backed day also requires confirmation of its gross-charge basis and applicable tariff treatment before any reporting approval. Keep separate reward ledgers intact. No approval is inferred from source type or from a missing reward row.

The hypothetical reporting projection is implemented and exercised in tests; it is not a publication of corrected live values. Final live financial activation remains held for unverified charge bases. Release identity and publication remain subject to the overnight control acceptance and final CI, not to recurring CSV uploads.

## Autonomous operation requirement

Normal operation must not depend on manually supplied CSV exports, statements, local bootstrap files or a ChatGPT session. The existing 30-minute supplier observation and persistent interval store remain the primary intake; Recorder recovery fills eligible retained gaps. Exact Happy Hour charge comparisons now work with matching automatic integration charges alone. Optional CSV observations are separate corroboration, not a gate; disagreements are reported instead of silently selecting a correction. Incomplete or unavailable automatic evidence remains pending, and estimates never become supplier-settled by inference.

The automatic comparison is reporting-only. A future automatic adjustment must use the same gross charge and reward basis and a single canonical publication path for actual ROI, dashboard and WhatsApp. Until then preserve native operational estimates, existing credits and separate provenance. A supplier settlement feed is not currently implemented; lack of settlement evidence is an accounting status, not a reason to require recurring uploads or interrupt energy management.

### Automatic recovery and settlement boundary

The historical Recorder scan now includes independently mapped previous electricity consumption sensors as well as their estimated-cost sensors. Recover each source separately; a priced row alone must not stand in for independent consumption evidence. Missing meter days across the bounded 84-day lookback (ending three calendar days before the scan, after each direction's first complete retained meter day and commissioning) prevent a premature price-coverage stop. Earlier unobserved export history is not assumed missing. Failed query batches retry at the same cursor after one hour; an exhausted bounded scan retries after seven days, unless coverage has since recovered. The regular live scan and Power Down baseline capture remain independent. These cadences are conservative implementation defaults, not supplier guarantees.

A future read-only supplier settlement intake can use Octopus's documented GraphQL account transaction connection: https://developer.oegb-kraken.energy/guides/graphql/api-basics/ and https://developer.oegb-kraken.energy/graphql/reference/interfaces/accountinterface/ . The schema exposes transaction identity, posted date, reason, amount and reversal/issued flags (https://developer.oegb-kraken.energy/graphql/reference/objects/credit/). Actual customer permissions and event-level identifiers must be validated on the installed system before matching any credit; an account credit amount or posting date alone does not identify a Happy Hour or prove an EV discount. No credentials are requested in chat or placed in GitHub. No new API client, authentication or live settlement authority is introduced by this change.

### Final recovery hardening

A pending Recorder result is discarded if its entity mapping changes during the scan, including a change away and back. The original persisted evidence is retained; this guard does not reinterpret old rows as belonging to a different meter or migrate existing meter history. The diagnostic sensor `sensor.kems_financial_recovery` exposes cached recovery status, missing meter and price counts, unmatched/conflicting intervals, next retry and pending/unsettled reward amounts. Retained estimates being complete is not supplier settlement. No new supplier requests are made by the sensor.
