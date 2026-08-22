# Alpha8 product-presentation canonicalisation

Alpha7.36 is now owned by one canonical non-versioned presentation boundary while preserving the proven runtime behavior exactly.

- `agile_product_presentation.py` is the canonical installer.
- `agile_panel_presentation_runtime.py` is byte-for-byte identical to `agile_alpha736_panel_flow.py`.
- `dashboard_product_finance_runtime.py` is byte-for-byte identical to `dashboard_alpha736_finance.py`.
- Installation order remains panel flow projection first, finance/dashboard presentation second.
- Historical Alpha7.36 files remain in the tree as regression evidence but are no longer executable through `agile_alpha7_compat.py`.

The panel layer remains reporting-only. It republishes the final `current_routing_snapshot` into the compact ESPHome feed, keeps the legacy panel entity for already-flashed units, and exposes simulated SOC in the live scenario. It does not modify dispatch, rolling planning, tariffs, optimisation, commissioning, or hardware-write permissions.

The dashboard layer retains comparison completeness, explicit unavailable-data labels, winner-by-period evidence, and the Cost & ROI view. No version, release, Web, PWA, panel firmware, remote-access, or commissioning change is part of this cleanup slice.
