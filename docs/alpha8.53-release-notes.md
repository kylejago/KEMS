# KEMS 0.8.0-alpha8.53

Alpha8.53 is a managed-dashboard rendering-only release that fixes the full-width Agile Plan table introduced in Alpha8.52. It does not change optimiser, routing, settlement, accounting, Power Down, EV policy, FoxESS control, or the hardware-write boundary.

## Continuous Markdown table rows

Alpha8.52 correctly moved the detailed Today/Tomorrow slot plan to a native full-width Home Assistant panel, but Home Assistant rendered only the six-column header as a table. The slot rows appeared as plain text with literal `|` separators because Jinja control and assignment statements emitted blank lines between the Markdown table separator and each generated row.

Alpha8.53 uses Jinja left-whitespace control for the detailed Agile table loop and its assignments. The rendered Markdown is now contiguous:

```text
| Time | Price | Est. SOC | Grid | Solar | Battery |
|---|---:|---:|---|---|---|
| 16:30 | 23.57p | 68.7% | EXPORT · 3.90 kWh | HOME/EXPORT · 2.30 kWh | EXPORT · 2.10 kWh |
| 17:00 | 23.93p | 64.0% | EXPORT · 2.85 kWh | HOME · 0.45 kWh | EXPORT · 2.85 kWh |
```

The table remains sourced only from the canonical Alpha8.48+ `flow_*` presentation fields.

## Exact route-label expansion

The new rendered regression also reproduced the `EXPORTRT` text visible in the Alpha8.52 field screenshot. The old dashboard helper used a raw `replace('EXPO', 'EXPORT')`; because the canonical standalone label is already `EXPORT`, that substring replacement turned `EXPORT` into `EXPORTRT`.

Alpha8.53 removes substring replacement entirely. It uses an exact display-label lookup for the compact mixed-route vocabulary emitted by the canonical slot-flow contract. A legitimate canonical `EXPORT` therefore remains `EXPORT`, while compact mixed labels such as `HOME/EXPO` display as `HOME/EXPORT`. This is presentation-only; the canonical `flow_*` values are unchanged.

## Rendered regression proof

The dashboard regression suite now renders representative Agile slot data with Jinja2 and asserts that:

- the header, separator and data rows are consecutive Markdown lines;
- there is no blank line before the first data row;
- the user's mixed-flow example renders as Solar `HOME/EXPORT · 2.30 kWh`, Battery `EXPORT · 2.10 kWh`, and Grid `EXPORT · 3.90 kWh`;
- canonical `EXPORT` is never mutated to `EXPORTRT`;
- canonical `flow_*` fields remain the only routing and energy source for the table.

Jinja2 is added only to the development/test requirements so CI can prove the rendered Markdown structure. There is no new runtime dependency for KEMS.

## Regression boundary

- Existing canonical slot-flow reconciliation remains authoritative.
- No Agile optimiser or dispatch ownership changes.
- No settlement/accounting changes.
- Power Down behaviour is unchanged.
- KEMS Web / Pi / PWA remains `0.8.0-alpha8-web.7`.
- managed ESP32 panel remains `0.8.0-alpha8-panel.1`.
- Real FoxESS hardware writes remain blocked.
