# Alpha8 operator telemetry canonicalisation

Alpha8 retires both Alpha7.42 Full KEMS Agile dashboard modules from the executable compatibility registry.

The canonical boundary is `agile_operator_telemetry.install_operator_telemetry`. It preserves the proven historical order:

1. focused Full KEMS Agile dashboard plus simulated power and live-today summary telemetry;
2. recorder-friendly actual power graph telemetry and the focused-view entity substitution.

For this parity slice, `agile_operator_dashboard_runtime.py` is byte-for-byte identical to `agile_alpha742_dashboard_focus.py`, and `agile_live_graph_runtime.py` is byte-for-byte identical to `agile_alpha742_live_graph_telemetry.py`. The historical files remain in the repository as regression evidence but are no longer executable compatibility entries.

The behavior contract is unchanged: missing physical solar, battery, or export data remains unavailable rather than being replaced with zero; simulated and actual graph entities keep their existing recorder-friendly units and state classes; the Full KEMS Agile operator view retains the same content and sensor IDs.

This work is reporting-only. It does not alter Agile dispatch, rolling-plan arithmetic, reserve policy, price handling, tariff logic, commissioning state, or hardware-write permissions. Real FoxESS hardware writes remain blocked.
