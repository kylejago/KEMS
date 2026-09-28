# Alpha9.71 — preserve the non-cheap FoxESS MinSOC baseline

Live Alpha9.70 commissioning proved that enabling Master Control could raise FoxESS MinSOC-on-grid from the pre-KEMS 10% baseline to the 15% KEMS planning reserve outside a cheap period. On the commissioned KH7 this caused paid grid import to charge the battery back toward 15%, contrary to the No Paid Export / no-paid-import operating policy.

Alpha9.71 separates those meanings. The KEMS normal reserve remains a planning and discharge target, but outside a confirmed cheap period the reviewed live Self Use backend writes the captured pre-KEMS MinSOC-on-grid baseline instead of the planning reserve. If KEMS cannot prove and preserve that captured baseline, the write fails closed and ownership is restored.

Confirmed-cheap behaviour is intentionally unchanged. Force Charge may still use the solar-aware no-export target, and the Alpha9.70 EV battery-hold fallback may still raise MinSOC to its latched physical SOC guard during a genuinely confirmed cheap EV session. When the cheap period ends, the physical MinSOC target returns to the pre-KEMS baseline.

This patch adds no Force Discharge authority, no import/export power-limit writes, no direct Ohme control, no automatic Master Control enable and no commissioning bypass. Issue #297 remains the separate path toward physically proven house-only battery / EV-grid allocation.
