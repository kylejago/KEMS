# Alpha8 bounded partial-horizon canonicalisation

Alpha7.28 bounded partial-horizon dispatch now has a canonical Alpha8 ownership boundary. `agile_bounded_partial.py` owns live installation and `agile_bounded_partial_runtime.py` is the exact historical Alpha7.28 Git blob, so this slice is an ownership migration rather than a dispatch-policy rewrite.

The runtime still depends on the proven Alpha7.17 dispatch, Alpha7.23 shadow, Alpha7.25 non-zero proof, Alpha7.26 provisional planning, rolling-plan and runtime-base objects. Those dependencies are intentionally not rewritten in this slice. Later solar-headroom installation continues to wrap the same shared rolling and shadow objects after bounded-partial installation.

Historical `agile_alpha728_bounded_partial.py` remains in the tree as regression evidence, but it is no longer an executable compatibility-registry entry. The canonical price-recovery layer remains immediately before bounded partial, and canonical live routing remains immediately after it.

All commissioning safeguards remain unchanged: simulation/shadow only, Home Assistant hardware service calls absent, FoxESS writes absent, `safe_to_write_hardware` remains false, and real hardware writes remain blocked.
