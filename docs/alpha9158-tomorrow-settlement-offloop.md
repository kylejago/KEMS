# Alpha9.158 — awaited Tomorrow settlement projection

Baseline: 0.9.0-alpha9.157 (486facbf729801af5a91cf15dbc2fae5fd742eff).

Run the pure `_compare_day(..., projection=True)` from the settled Tomorrow handoff through the HA executor, matching the existing Agile day manager. Await its exact result **within the same coordinator scan**, before control/reporting continues. The mandatory pre-control settlement, changed post-shadow evidence replay, first publication, exact Tomorrow equality gate and conditional second publication remain unchanged. A missing executor falls back to the existing direct synchronous compare.

Settlement diagnostics expose `tomorrow_compare_executor_offloaded`. Its `tomorrow_compare_thread_cpu_seconds` measures the calling thread (not executor worker CPU when offloaded). No promise of faster total scan wall time without live data.

Unchanged: live FoxESS/EV commands, 7 kW DNO export cap, 15% SOC planning target/10% floor, power-balance commissioning, current/tomorrow tariff inputs, Power Down, Happy Hour and 06:00–06:30 safe-first installation policy.

Validate full Python, Black, Ruff, HACS, Hassfest CI; regression tests cover awaited executor and exact Tomorrow correction publications.
