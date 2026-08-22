# Alpha8 live-registry closure

This slice records **registry closure** for the Alpha8 refactor/parity baseline. It does not migrate another runtime.

## Dashboard consolidation inspection

`dashboard_consolidation.py` is already a functional, non-versioned owner. It was introduced for the Alpha7.18 dashboard consolidation in commit `518e45cf6b0a8474f7e5f33eb76a0bf8027104aa`; that original compositor blob was `e17b3d182c43c053a89a27d4812d1b35f2adb50f`.

The same module was deliberately evolved in place for the Alpha7.35 nine-page product dashboard. On the Alpha8.0 cleanup baseline before this closure slice its current blob is `26a965828995598f3965065132041d8452a08ecb`.

There is no separate `agile_alpha7xx` dashboard-consolidation runtime, no frozen downstream import of a historical consolidation module name, and no module-identity bridge to preserve. The compositor owns `consolidate_dashboard()` directly and installs by wrapping `dashboard._combined_master_dashboard_bytes` with its idempotence marker.

**No dashboard runtime is copied, renamed or wrapped** by this cleanup. Creating another facade/runtime pair would add indirection without retiring any historical executable owner.

## Live registry state

After the staged Alpha8 cleanup slices, both `PRE_BASE_PATCHES` and `POST_BASE_PATCHES` contain functional module names only. No registry entry matches the historical `agile_alpha7xx...` runtime naming pattern.

`dashboard_consolidation` intentionally remains between canonical validation evidence and the canonical validation-dashboard installer. This preserves the proven Alpha7.19 ordering contract while keeping the compositor itself as the direct owner.

Historical Alpha7 modules remain packaged as regression evidence. `agile_smart_export_runtime.py` also retains `ALPHA7_COMPATIBILITY_ORDER` as non-executable compatibility metadata. This closure does not archive or delete that evidence.

## Scope

The only executable-source change is wording in the `agile_alpha7_compat.py` module documentation/comments so they describe the now-closed live registry accurately. Installer tuples, installer order and callable bodies are unchanged.

There is no tariff, dispatch, SOC, reserve, export, deadline, dashboard rendering or commissioning behavior change. KEMS remains `0.8.0-alpha8.0`; there is no release, tag or version bump.

The dashboard compositor does not call Home Assistant services or a FoxESS provider and cannot set `safe_to_write_hardware` or `commands_permitted`. Commissioning remains mandatory and **real hardware writes remain blocked**.
