# Alpha8 non-zero proof and provisional-planning canonicalisation

This cleanup slice moves executable ownership of the proven Alpha7.25 non-zero export proof and Alpha7.26 provisional planning layers behind one non-versioned Alpha8 boundary. It is an ownership migration only; it does not change policy, dispatch, price-recovery semantics, SOC planning, or commissioning state.

The canonical runtime files reuse the exact historical Git blobs:

- Alpha7.25 `agile_alpha725_nonzero.py` -> `agile_nonzero_export_proof_runtime.py`: `e3a5319366ec1d1351e1ee8b18ad7899de432d71`
- Alpha7.26 `agile_alpha726_provisional.py` -> `agile_provisional_planning_runtime.py`: `ff8c3190cb0eeb1801cbfd312fe49d6800fc14e5`

No runtime body is rewritten.

## Why the pair moves together

Alpha7.27 price recovery is already canonical, but its frozen byte-identical runtime imports `agile_alpha726_provisional` and calls the installer-populated module global `alpha726_original_fetch_rates`. A separately imported copy of Alpha7.26 would therefore break the wrapper chain even if its bytes were identical.

Canonical Alpha7.28 bounded-partial routing also retains frozen imports of both `agile_alpha725_nonzero` and `agile_alpha726_provisional` for the strict candidate-applied replay and unresolved-slot capacity helper.

`agile_proof_planning.py` therefore binds those two historical import names to the canonical byte-identical runtime module objects before the downstream Alpha7.27 and Alpha7.28 runtimes are imported. This is the same narrow object-identity technique used by the proven Alpha8 current/solar routing boundary; it is not a general compatibility alias layer.

## Preserved Alpha7.25 contract

The non-zero proof still requires a genuine optimiser export above 0.01 kW, a complete and unheld price horizon, Feed-in First routing, grid export permission, 13/13 independent safety, the existing battery/inverter/SOC limits, and 100% strict target/outcome tracking within 0.01 kW. It remains a candidate-applied digital-twin proof and keeps `safe_to_write_hardware` false.

## Preserved Alpha7.26 contract

Provisional planning still keeps executable export at zero while an incomplete price horizon is held, retains the known-price economic allocation, reserves full unresolved-slot discharge capacity, performs at most four targeted price retries, and publishes both conservative hold and provisional SOC evidence. Missing prices are never invented.

## Safety and release boundary

This slice does not add Home Assistant hardware service calls or FoxESS provider writes. Simulation/shadow remains authoritative, real hardware writes remain blocked, and the integration version remains `0.8.0-alpha8.0`. Historical Alpha7.25 and Alpha7.26 files and historical compatibility-order metadata remain in the repository as regression evidence.
