# Alpha8 price-publication canonicalisation

Alpha8 now owns the proven Alpha7.41 progressive Agile price-publication behavior through the canonical `agile_price_publication` boundary.

The historical Alpha7.41 runtime and dashboard modules remain in the repository as regression evidence, while `agile_price_publication_runtime.py` and `dashboard_price_publication_runtime.py` are byte-identical canonical runtime owners for this parity slice.

The canonical installer preserves the original order: price-publication runtime first, dashboard publication visibility second.

Behavior is unchanged: only clean Octopus publication-pending gaps may use the bounded known-price planner, unpublished prices are never guessed, unknown-slot discharge opportunity remains fully reserved, the current settlement period still requires a real price before deliberate battery export, and the 10% reserve plus inverter/export limits remain intact.

This cleanup does not change dispatch, rolling-plan, tariff, forecast, commissioning or hardware-write permissions. Real FoxESS hardware writes remain blocked.
