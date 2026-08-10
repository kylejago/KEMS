# KEMS 0.7.0-alpha5 in-place development upgrade

This build preserves all 0.6.0-beta1 observation history, learning data, source mappings, simulation totals, Power Down planning, and ROI state.

It adds new options and calculated entities for the Control Lab. Existing config entries migrate to schema version 11 and receive safe defaults automatically.

No real inverter or charger service calls are made. The real control backend is intentionally unavailable until the KH7 is installed and commissioned.
