# Alpha8 economic opportunity canonicalisation

Alpha8 now owns the proven Alpha7.40 proactive Agile opportunity guard through the canonical `agile_economic_opportunity` boundary.

The planning runtime and Agile-first dashboard runtime are retained byte-for-byte from Alpha7.40. The canonical facade installs the planning guard first and the dashboard second, preserving the historical execution order.

The guard may only move already-planned battery export into the current settlement period when that period protects a stronger economic outcome. It does not increase exportable energy, does not weaken the 10% SOC floor, and does not override `maximum_discharge` or `target_reached` deadline modes.

Battery export remains bounded by the configured export limit, shared inverter headroom, maximum discharge limit, and the effective safe discharge path. Real FoxESS hardware writes remain blocked by the existing commissioning boundary.

This is an Alpha8 ownership/refactor slice only. It does not change tariff logic, price thresholds, uncertainty margin, dispatch policy, dashboard calculations, commissioning state, or release version.
