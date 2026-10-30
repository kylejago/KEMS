# Alpha9.161 targeted settlement publication reduction

30 October 2026 Alpha9.160 diagnostics: KEMS coordinator 13.911s at 07:38,
pre-control settlement 6.373s, true settlement arithmetic 0.001s, nested
repeated publications ~1.06s each. Historical worker ~1.2s.

The underlying settlement and reporting methods still execute synchronously
and in the same order. During each pre-control or post-shadow settlement pass,
a repeated Home Assistant async_set is suppressed **only** when the exact
current HA state and attributes match the new state and attributes, and only
after that specific entity was written earlier in the same pass.

This is deliberately more conservative than PR #404: any changed cheap-start
SOC, Tomorrow slot, Agile rate, export value, flow, or any other attribute is
published immediately. Existing HA state reads by reporting wrappers continue
to see each real change. The per-pass scope is dropped on success and exception.
No control writer, EV policy, reserve, grid cap, or rollback change.

Diagnostics include per-pass attempts, comparisons, identical writes skipped,
actual writes, and comparison overhead. This initial change targets entity
publication overhead; it does not claim to eliminate slow CPU-heavy planning
calculations. Validate again with 03:15–07:30 live diagnostics before considering
additional coalescing or off-main-thread work.
