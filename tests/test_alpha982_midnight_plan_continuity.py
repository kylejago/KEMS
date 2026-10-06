    state = _state()
    state["tomorrow_slots"][1]["battery_export_kwh"] = None
    # Presentation zero must never turn an unknown authoritative value into zero.
    state["tomorrow_slots"][1]["flow_battery_export_kwh"] = 0.0
    old_second = state["tomorrow_slots"][1]["flow_estimated_soc_percent"]

    assert _function()(state, config=_config()) == 1
    assert state["tomorrow_slots"][1]["flow_estimated_soc_percent"] == old_second
    assert (
        "components unavailable"
        in state["tomorrow_display_continuity"]["stopped_reason"]
    )


def test_alpha982_runtime_installs_continuity_after_safety_floor() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert "build_tomorrow_display_continuity_manager" in source
    assert "_safety_floor_manager = build_safety_floor_manager(" in source
    safety_index = source.index("_safety_floor_manager = build_safety_floor_manager(")
    continuity_index = source.index(
        "EfficientAgileSmartExportManager = build_tomorrow_display_continuity_manager("
    )
    assert continuity_index > safety_index
    assert "_safety_floor_manager\n)" in source[continuity_index:]


def test_alpha982_continuity_is_reporting_only() -> None:
    source = CONTINUITY.read_text(encoding="utf-8")
    assert '"hardware_writes": "blocked"' in source
    assert "services.async_call" not in source
    assert "async_call(" not in source
    assert "foxess" not in source.lower()