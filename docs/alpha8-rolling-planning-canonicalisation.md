# Alpha8 rolling planning canonicalisation

This change is an **ownership migration only**. It moves the proven Alpha7.16 rolling-replan behavior and rolling-plan dashboard presentation behind a non-versioned Alpha8 ownership boundary without rewriting either historical runtime.

The canonical runtime `agile_rolling_replan_runtime.py` retains exact blob `b5bfcd1f93f6afea29f71155e49d97af4f074232`, matching historical `agile_rolling_replan.py`. The canonical dashboard runtime `agile_rolling_dashboard_runtime.py` retains exact blob `d5ef0f9f8871bb76fe6f2966e284d8d2b6ad771f`, matching historical `agile_alpha716_dashboard.py`.

A narrow compatibility bridge binds the historical `agile_rolling_replan` module name to the canonical rolling runtime object. This is required because frozen Alpha7.17 dispatch and later retained/canonical runtimes import that historical name and patch or call the shared rolling object. The dashboard module has no corresponding module-identity dependency and is not aliased.

Historical installation timing is preserved: rolling replanning remains the first post-base compatibility layer, while the rolling dashboard still installs after the Alpha7.14/7.15 history presentation and before the Alpha7.17 dashboard refinement. Alpha7.17 dispatch itself is unchanged by this slice.

The retained behavior continues to re-evaluate the remaining export plan on each coordinator scan, protect predicted house energy, preserve price ranking until deadline capacity becomes pressured, use the transient history overlay without increasing normal persistence frequency, and publish the rolling plan as simulation-only evidence.

No tariff, reserve, discharge, export, SOC, commissioning, provider, or hardware-control policy changes are introduced. No Home Assistant hardware service call or FoxESS write path is added; `safe_to_write_hardware` and `commands_permitted` are not enabled, and **real hardware writes remain blocked**.

KEMS remains `0.8.0-alpha8.0`; this cleanup does not create a release, tag, or version bump.
