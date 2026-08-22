# Alpha8 price-recovery canonicalisation

Alpha7.27's observable Agile missing-price recovery is now owned by the canonical `agile_price_recovery` boundary.

The runtime is copied byte-for-byte into `agile_price_recovery_runtime.py`. The executable Alpha7 compatibility registry calls the canonical installer, while the historical `agile_alpha727_price_recovery.py` file remains unchanged as regression evidence.

Alpha7.28 remains deliberately historical in this slice. It consumes Alpha7.27's published `_kems_alpha727_price_fetch_diagnostics` state but does not import or patch the Alpha7.27 module object, so no compatibility alias is required.

This migration does not change exact-slot retries, context-window retries, Octopus-gap classification, provisional-plan behaviour, bounded-partial dispatch, optimiser policy, tariff handling, SOC policy, or any hardware-write gate. Real FoxESS writes remain blocked.
