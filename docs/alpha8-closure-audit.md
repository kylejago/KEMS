# Alpha8 closure audit — residual historical import identity

## Baseline

This audit starts from signed `main` commit
`3cc55f374e03f326211f743ac5b2f2a0eecd09fc`, the PR #131 live-registry
closure baseline.

PR #131 proved that the executable PRE/POST compatibility registries contain
functional canonical owners rather than version-named `agile_alpha7xx` owner
entries. This follow-up checks a different question: whether frozen or later
canonical modules still import historical Alpha7 names that can resolve to a
second historical module object instead of the canonical runtime object.

## Finding

Most remaining version-named imports were already intentional object-identity
compatibility references with explicit `sys.modules` bridges. The audit found
three residual names that did not yet have that bridge:

- `agile_alpha728_bounded_partial`
- `agile_alpha734_deadline_guard`
- `agile_alpha741_partial_publication`

These names are still referenced by downstream parity code. Without a bridge,
Python can load the packaged historical file as a second module object. A later
patch can then mutate that duplicate while the live canonical runtime continues
using another object.

This is ownership/identity debt, not a request to change optimiser behaviour.

## Repair

The historical names are redirected to their already-existing canonical runtime
objects:

| Historical import name | Canonical runtime owner | Exact parity blob |
| --- | --- | --- |
| `agile_alpha728_bounded_partial` | `agile_bounded_partial_runtime` | `b6b06ecea370050eb663a5bf03baf53d6e4d401c` |
| `agile_alpha734_deadline_guard` | `agile_deadline_guard_runtime` | `e4423b3bf55a64f91baaa07fc72eaa4f54ce38cf` |
| `agile_alpha741_partial_publication` | `agile_price_publication_runtime` | `5321a95a4954a47ba6eb8511c41f44c2aed8fdfd` |

The runtime blobs themselves are not edited. Each bridge therefore changes only
module identity: historical imports receive the same byte-identical canonical
object that the live Alpha8 owner already installs.

Installation order is preserved. Bounded partial ownership is installed before
price publication, deadline guard before deadline-plan reconciliation, and price
publication before publication reporting.

## Mechanical closure contract

`tests/test_alpha8_closure_audit.py` scans every top-level KEMS Python module with
AST rather than relying on repository text search.

For every version-named `agile_alpha7xx` import outside historical evidence it
requires an explicit `_bind_legacy_name(...)` bridge. Every versioned bridge must
point to a canonical runtime file that is byte-for-byte identical to the matching
historical Alpha7 evidence file. Frozen runtime copies that themselves retain
version-named imports must also remain exact packaged historical blobs.

This lets old source text remain frozen where byte parity matters while proving
that execution resolves through canonical module objects. If another unbridged
historical dependency appears, the contract fails rather than silently loading a
duplicate module.

## Closure decision

Once the full exact-head validation suite passes, the live Agile chain has zero accidental residual historical dependencies. Remaining `agile_alpha7xx` source
references are then either packaged regression evidence or explicitly bridged
compatibility references whose runtime identity is canonical and byte-identical.

No tariff, dispatch, reserve, SOC, deadline, export, dashboard, commissioning or
hardware-control policy is changed by this audit. No Home Assistant hardware
service call or FoxESS provider write is added. The safety result is explicit: real hardware writes remain blocked. The integration remains
`0.8.0-alpha8.0`; there is no release, tag or version bump in this closure slice.
