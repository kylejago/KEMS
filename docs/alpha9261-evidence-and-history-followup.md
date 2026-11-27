# Alpha9.261 evidence and history follow-up

The 27 November live .260 snapshot showed 576 newly retained charge observations
and six new complete priced days for each electricity direction. The next
Recorder query progresses in fixed seven-day windows, at most twelve per setup;
an empty window or error stops recovery. No data are fabricated for purged
history. Charge rows still require exact energy matches; no ledger or ROI write.

Power Down 9019 operated physically and the post-event Agile budget reconciled.
The previous baseline scan missed the later provider update; BottlecapDave
v19.3.0 builds per-period baselines and clears attributes when no target is
available. The new minute cadence preserves exact joined identity and reward
rate and independently retains only explicitly complete, timestamp-aligned
rows. Incomplete or conflicting evidence never becomes an exact reward.
No assumption that today's baseline has been recovered.

The provider's v19.3.0 gas previous-accumulative sensor exposes calorific_value;
its conversion is volume * 1.02264 * calorific_value / 3.6. Four paired nonzero
observations imply approximately 975 MJ/m3, compared with the provider default
40.0. The actual setting is not yet observed. Check it in the next diagnostic
and verify against a supplier CSV before considering any corrected evidence.
No automatic adjustment, promotion or gas ledger changes.

The eight retained cheap-period discharge samples on Nov 25 and 26 precede the
Nov 26 16:39 GMT .255 fix release. Two were Self Use/release and six were
Force Charge reapplication samples (writes after physical observation). That
is not proof of sustained discharge after reapplication. Keep all protective
controls intact and distinguish post-fix recurrence from the retained history.
The shared AC bus has not proven EV/house independent routing.

Historical warm-cache hits still verify all exact source values with SHA-256;
mutable Snapshot fields and late backfills prevent safe timestamp-only keys.
Avoid redundant summary mapping allocation and expose serialization versus
digest cost. No claimed material speedup until live measurements. A more
substantial generation-based cache requires a separately reviewed immutable
input ownership contract, not a weakened safety or exactness check.
