# KEMS 0.9.0-alpha9.183 — KEMS-only stability and reporting

This maintenance candidate responds to field diagnostics on 3–5 November 2026.

- **Agile settlement publication:** the synchronous final deadline owner now
  suppresses one redundant intermediate FlowPresentation Home Assistant state
  publication. All settled-SOC calculations, flow-contract reconciliation,
  and the final publisher remain in their existing order. The defer flag is
  restored in a finally block. No delayed queue or changed FoxESS authority.
- **Scan diagnostics:** expose coordinator thread CPU alongside elapsed wall
  time so overnight 03:00–05:00 latencies can be separated from CPU work.
  No claim that a long wall scan proves an event-loop block.
- **ROI dashboard:** tolerate nullable/historic reward-audit event fields;
  keep provisional credits and supplier-unconfirmed values clearly labelled.
- **Lifetime counters:** correctly label historically adjustable household
  and whole-home energy totals as TOTAL rather than TOTAL_INCREASING. Do not
  hide or discard actual historic meter corrections.
- **Cheap-period UI:** replace expired pre-cheap bridge action text in the
  read-only next-action sensor when Force Charge is selected. Suppress the
  *projected-at-cheap-start* figure once charging has already begun, rather
  than misrepresenting a simulated reserve target as physical SOC.

Physical 10% house floor, 15% deliberate export target, 7 kW grid export
limit, 7 kW bounded charging, EV hold, and Happy Hour/Power Down control
remain untouched. Paid-export proof still needs 2 independent live samples.

Deployment: validate workflow, HACS, Hassfest, panel compilation and a fresh
post-install diagnostic. Do not install during charging or active paid export.
