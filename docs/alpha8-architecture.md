# Alpha8 architecture closure

## Status

The Alpha8 ownership and compatibility migration is complete.

The closure point is signed `main` commit
`b84ce059020d0145527595c4d4680605eff3c276` (PR #132), tree
`13942f2958a9d174d8b58737dbc3d0aed89e0725`.

Alpha8 remains a behaviour-preserving consolidation baseline at
`0.8.0-alpha8.0`. Closing the migration does not itself change optimiser,
tariff, routing, SOC, reserve, deadline, export, dashboard, commissioning or
hardware-control behaviour.

## Canonical ownership model

Live Agile behaviour is owned through purpose-named canonical modules and the
functional PRE_BASE / POST_BASE registry in `agile_alpha7_compat.py`.

Historical version-named `agile_alpha7xx` modules are not live registry owners.
They remain packaged only where they are required as frozen regression evidence
or by exact compatibility contracts.

No new version-named runtime patch chain is permitted. In particular, future
Alpha8 or later behavioural work must not introduce `agile_alpha8*.py` modules as
a release-by-release patch sequence. Behavioural changes belong in stable,
purpose-named modules with explicit tests and ownership.

## Deliberate compatibility bridges

Some frozen downstream layers still import historical Alpha7 module names and
expect mutations to occur on the same module object used by the canonical
runtime. In those cases, a narrow `_bind_legacy_name(...)` bridge intentionally
rebinds the historical import name to the canonical byte-identical runtime
object.

These bridges are architectural compatibility contracts, not cleanup debt to be
removed for naming consistency.

A bridge may be removed only when all of the following have been proved on one
exact candidate head:

1. no frozen or canonical downstream consumer still imports, patches, mutates or
   reads the historical module object;
2. the Alpha8 closure audit reports no residual dependency on that historical
   name;
3. all byte-parity and historical regression contracts remain valid without the
   bridge;
4. the complete exact-head validation suite passes after the removal.

## Historical Alpha7 evidence boundary

Historical Alpha7 source files remain regression evidence for the proven
Alpha7.52 behaviour baseline. Their continued presence is intentional while
frozen runtimes, byte-parity assertions or compatibility tests depend on them.

Historical files must not be renamed, rewritten, archived or deleted merely to
make the repository look more uniform.

A historical Alpha7 file may be considered for archival only when:

- no live canonical module imports it directly;
- no deliberate compatibility bridge targets or depends on its module identity;
- no frozen runtime requires its object identity;
- no byte-identical parity assertion uses it as reference evidence;
- no regression, dashboard, migration or historical reconstruction test relies
  on it being packaged;
- the mechanical closure audit and the full regression suite remain green after
  its removal from the live package;
- archival is performed as a separate, reviewable change rather than bundled
  with behavioural development.

Until all of those conditions are satisfied, the file remains part of the
supported Alpha8 compatibility evidence set.

## Mechanical closure contract

`tests/test_alpha8_closure_audit.py` is the regression contract for this
architecture.

It mechanically checks residual version-named imports, explicit canonical
bridges, byte-identical historical/runtime parity, frozen runtime parity, live
registry closure, the `0.8.0-alpha8.0` version boundary, absence of a new
`agile_alpha8*.py` chain and preservation of the real-hardware write block.

Do not weaken this test simply to make a future cleanup or refactor pass. A
failure should be treated as evidence that the proposed change crossed an Alpha8
architecture boundary and must be understood explicitly.

## Behavioural development boundary

PR #132 is the final ownership/identity cleanup slice. Work after this closure
point should be classified as one of:

- behavioural development in canonical purpose-named modules;
- observability, validation or documentation work;
- commissioning-readiness work that keeps real hardware writes disabled;
- a separately justified archival/migration change that satisfies the historical
  evidence criteria above.

Do not resume cosmetic canonicalisation after this point.

Any behavioural development must preserve the existing safety and operating
contracts unless the change explicitly and deliberately modifies them with new
regression evidence.

## Hardware and commissioning boundary

Alpha8 remains simulation/shadow only for real FoxESS control until actual
commissioning requirements are satisfied.

The following safety results remain mandatory:

- `commands_permitted=False`
- `safe_to_write_hardware=False`
- `real_backend_available=False`
- `"hardware_writes": "blocked"`

Documentation closure does not authorize Home Assistant hardware-control service
calls, FoxESS provider writes or commissioning bypasses.

Commissioning-readiness work may prepare read-only discovery, backend interface
verification, command-envelope validation, dry-run comparison and explicit
operator enable gates, but must not activate real writes.

## Exact-head development discipline

Future slices continue to use the established exact-head workflow:

1. inspect and record current `main` SHA/tree;
2. branch from that exact SHA;
3. make the smallest dependency-safe change;
4. freeze one candidate head;
5. run every required CI gate on that exact head;
6. discard previous CI evidence if the candidate changes;
7. keep the PR draft until all required gates are green;
8. re-check head/base and unchanged `main` before marking ready;
9. squash merge with `expected_head_sha`;
10. verify the post-merge SHA/tree/parent/signature/version/safety invariants.

The real ESPHome firmware compile remains part of the normal final gate.

## Closure decision

Alpha8 ownership/compatibility cleanup is closed.

The canonical architecture, deliberate legacy identity bridges, frozen Alpha7
regression evidence and hardware-write boundary now form the baseline for the
next KEMS phase. Future work should build forward from these boundaries rather
than reopening the version-named patch architecture that Alpha8 removed.
