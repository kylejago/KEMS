from pathlib import Path

ROOT = Path(__file__).parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


models = ROOT / "custom_components/kems/kems_core/models.py"
replace_once(
    models,
    "    next_offpeak_start: datetime | None = None\n"
    "    offpeak_end: datetime | None = None\n\n"
    "    saving_session_joined: bool = False\n",
    "    next_offpeak_start: datetime | None = None\n"
    "    offpeak_end: datetime | None = None\n"
    "    intelligent_slot_confirmation: str | None = None\n"
    "    intelligent_slot_evidence: dict[str, Any] = field(default_factory=dict)\n\n"
    "    saving_session_joined: bool = False\n",
)

collector = ROOT / "custom_components/kems/collector.py"
replace_once(
    collector,
    '        """Initialise the coordinator."""\n',
    '        """Initialise the collector."""\n',
)

simulation = ROOT / "custom_components/kems/kems_core/simulation.py"
old_sim = '''            elif current.cheap_period_confirmed:
                if no_export_mode:
                    solar_to_home = min(
                        solar_energy,
                        actual_house_kwh,
                        inverter_capacity,
                    )
                    interval_solar_to_home = solar_to_home
                    house_grid_kwh = max(actual_house_kwh - solar_to_home, 0.0)
                    solar_surplus_kwh = max(solar_energy - solar_to_home, 0.0)
                    forecast_required = self._no_export_requirement_after_cheap(
                        today,
                        index + 1,
                        config,
                        forecast_energy_until_offpeak_kwh,
                    )
                    target_stored_kwh = self._no_export_charge_target_stored_kwh(
                        forecast_required,
                        reserve_kwh,
                        capacity,
                        config,
                    )
                    charge_room_input_kwh = max(
                        target_stored_kwh - battery_kwh,
                        0.0,
                    ) / max(config.charge_efficiency, 0.01)
                    solar_charge_input_kwh = min(
                        solar_surplus_kwh,
                        max(config.max_charge_kw, 0.0) * hours,
                        charge_room_input_kwh,
                    )
                    stored_from_solar = (
                        solar_charge_input_kwh * config.charge_efficiency
                    )
                    battery_kwh += stored_from_solar
                    battery_charge += stored_from_solar
                    interval_solar_to_battery = stored_from_solar
                    remaining_charge_power_kwh = max(
                        max(config.max_charge_kw, 0.0) * hours - solar_charge_input_kwh,
                        0.0,
                    )
                    site_charge_headroom_kwh = float("inf")
                    if config.site_import_limit_kw is not None:
                        site_charge_headroom_kwh = max(
                            config.site_import_limit_kw * hours - house_grid_kwh,
                            0.0,
                        )
                    grid_charge_input_kwh = min(
                        remaining_charge_power_kwh,
                        max(target_stored_kwh - battery_kwh, 0.0)
                        / max(config.charge_efficiency, 0.01),
                        site_charge_headroom_kwh,
                    )
                    stored_from_grid = grid_charge_input_kwh * config.charge_efficiency
                    battery_kwh += stored_from_grid
                    battery_charge += stored_from_grid
                    interval_grid_to_battery = stored_from_grid
                    interval_import = house_grid_kwh + grid_charge_input_kwh
                    interval_export = 0.0
                    interval_curtailment = max(
                        solar_surplus_kwh - solar_charge_input_kwh,
                        0.0,
                    )
                else:
                    house_grid_kwh = actual_house_kwh
                    site_charge_headroom_kwh = float("inf")
                    if config.site_import_limit_kw is not None:
                        site_charge_headroom_kwh = max(
                            config.site_import_limit_kw * hours - house_grid_kwh,
                            0.0,
                        )
                    charge_input_kwh = min(
                        max(config.max_charge_kw, 0.0) * hours,
                        max(capacity - battery_kwh, 0.0)
                        / max(config.charge_efficiency, 0.01),
                        site_charge_headroom_kwh,
                    )
                    stored_from_grid = charge_input_kwh * config.charge_efficiency
                    battery_kwh += stored_from_grid
                    battery_charge += stored_from_grid
                    interval_grid_to_battery = stored_from_grid
                    interval_import = house_grid_kwh + charge_input_kwh
                    interval_export, interval_curtailment = self._limit_export(
                        solar_energy,
                        export_capacity,
                    )
                    interval_solar_export = interval_export
'''
new_sim = '''            elif current.cheap_period_confirmed:
                # Confirmed cheap import is the deliberate exception to normal
                # solar-to-home routing: Grid serves the house/EV while every
                # available unit of PV is offered to the battery first. Grid then
                # fills only the remaining battery charge request. This avoids
                # exporting PV while buying cheap energy to charge the battery.
                house_grid_kwh = actual_house_kwh
                if no_export_mode:
                    forecast_required = self._no_export_requirement_after_cheap(
                        today,
                        index + 1,
                        config,
                        forecast_energy_until_offpeak_kwh,
                    )
                    target_stored_kwh = self._no_export_charge_target_stored_kwh(
                        forecast_required,
                        reserve_kwh,
                        capacity,
                        config,
                    )
                else:
                    target_stored_kwh = capacity

                charge_power_budget_kwh = max(config.max_charge_kw, 0.0) * hours
                charge_room_input_kwh = max(
                    target_stored_kwh - battery_kwh,
                    0.0,
                ) / max(config.charge_efficiency, 0.01)
                solar_charge_input_kwh = min(
                    solar_energy,
                    charge_power_budget_kwh,
                    charge_room_input_kwh,
                )
                stored_from_solar = solar_charge_input_kwh * config.charge_efficiency
                battery_kwh += stored_from_solar
                battery_charge += stored_from_solar
                interval_solar_to_battery = stored_from_solar

                remaining_charge_power_kwh = max(
                    charge_power_budget_kwh - solar_charge_input_kwh,
                    0.0,
                )
                site_charge_headroom_kwh = float("inf")
                if config.site_import_limit_kw is not None:
                    site_charge_headroom_kwh = max(
                        config.site_import_limit_kw * hours - house_grid_kwh,
                        0.0,
                    )
                grid_charge_input_kwh = min(
                    remaining_charge_power_kwh,
                    max(target_stored_kwh - battery_kwh, 0.0)
                    / max(config.charge_efficiency, 0.01),
                    site_charge_headroom_kwh,
                )
                stored_from_grid = grid_charge_input_kwh * config.charge_efficiency
                battery_kwh += stored_from_grid
                battery_charge += stored_from_grid
                interval_grid_to_battery = stored_from_grid
                interval_import = house_grid_kwh + grid_charge_input_kwh

                solar_left_kwh = max(solar_energy - solar_charge_input_kwh, 0.0)
                if no_export_mode:
                    interval_export = 0.0
                    interval_curtailment = solar_left_kwh
                else:
                    interval_export, interval_curtailment = self._limit_export(
                        solar_left_kwh,
                        export_capacity,
                    )
                    interval_solar_export = interval_export
'''
replace_once(simulation, old_sim, new_sim)

agile = ROOT / "custom_components/kems/agile_smart_export.py"
old_agile = '''            if current.cheap_period_confirmed:
                grid_import = load_kwh
                target = capacity * _overnight_target(current, config) / 100
                solar_left = solar_kwh
                if rate <= 0:
                    charge = min(
                        solar_left,
                        charge_limit,
                        max(target - battery, 0) / max(config.charge_efficiency, 0.01),
                    )
                    solar_battery = charge * config.charge_efficiency
                    battery += solar_battery
                    solar_left -= charge
                    if charge:
                        actions.append("store solar")
                grid_charge = min(
                    max(
                        charge_limit
                        - solar_battery / max(config.charge_efficiency, 0.01),
                        0,
                    ),
                    max(target - battery, 0) / max(config.charge_efficiency, 0.01),
                )
                if config.site_import_limit_kw is not None:
                    grid_charge = min(
                        grid_charge,
                        max(
                            config.site_import_limit_kw * hours - grid_import,
                            0,
                        ),
                    )
                grid_battery = grid_charge * config.charge_efficiency
                battery += grid_battery
                grid_import += grid_charge
                if grid_charge:
                    actions.append("cheap charge")
                if rate > 0:
                    solar_export = min(solar_left, export_limit)
                    curtailed = max(solar_left - solar_export, 0)
                    if solar_export:
                        actions.append("export solar")
                else:
                    curtailed += solar_left
'''
new_agile = '''            if current.cheap_period_confirmed:
                grid_import = load_kwh
                target = capacity * _overnight_target(current, config) / 100
                solar_left = solar_kwh

                # Cheap import deliberately powers the house/EV from Grid. PV is
                # more valuable filling battery headroom than being exported while
                # Grid simultaneously charges the battery, so PV consumes the
                # shared charge-power budget before Grid charging is considered.
                solar_charge = min(
                    solar_left,
                    charge_limit,
                    max(target - battery, 0) / max(config.charge_efficiency, 0.01),
                )
                solar_battery = solar_charge * config.charge_efficiency
                battery += solar_battery
                solar_left -= solar_charge
                if solar_charge:
                    actions.append("store solar")

                grid_charge = min(
                    max(charge_limit - solar_charge, 0.0),
                    max(target - battery, 0) / max(config.charge_efficiency, 0.01),
                )
                if config.site_import_limit_kw is not None:
                    grid_charge = min(
                        grid_charge,
                        max(
                            config.site_import_limit_kw * hours - grid_import,
                            0,
                        ),
                    )
                grid_battery = grid_charge * config.charge_efficiency
                battery += grid_battery
                grid_import += grid_charge
                if grid_charge:
                    actions.append("cheap charge")

                if rate > 0:
                    solar_export = min(solar_left, export_limit)
                    curtailed = max(solar_left - solar_export, 0)
                    if solar_export:
                        actions.append("export solar")
                else:
                    curtailed += solar_left
'''
replace_once(agile, old_agile, new_agile)

# Remove the temporary helper before committing the real candidate.
workflow = ROOT / ".github/workflows/apply-alpha858-final.yml"
Path(__file__).unlink()
workflow.unlink()
