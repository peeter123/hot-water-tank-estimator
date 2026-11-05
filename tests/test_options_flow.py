"""Tests for the options flow: every value, the validation, and a reload that keeps the state (task 5.2)."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hot_water_tank_estimator.config_flow import (
    DRAW_TUNING,
    SHAPE_TUNING,
)
from custom_components.hot_water_tank_estimator.const import (
    CONF_AMBIENT_SENSOR,
    CONF_COLD_SENSOR,
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HISTORY_DAYS,
    CONF_HUMIDITY_SENSORS,
    CONF_LOCKS,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_VOLUME,
    CONF_WATER_METER,
    DOMAIN,
)
from custom_components.hot_water_tank_estimator.estimator import (
    TankConfig,
    TankEstimator,
)
from custom_components.hot_water_tank_estimator.setup_fit import History
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.util import dt as dt_util

from .common import (
    AMBIENT,
    COLD,
    FLOW,
    FULL_OPTIONS,
    HUMIDITY,
    RETURN,
    Rig,
    entity_id,
    set_sources,
    setup_entry,
    setup_fitted_entry,
    value,
)

TANK_FIELDS = {CONF_SENSOR_HEIGHT: 50}
SOURCE_FIELDS = {
    CONF_FLOW_SENSOR: FLOW,
    CONF_RETURN_SENSOR: RETURN,
    CONF_HUMIDITY_SENSORS: [HUMIDITY],
}


async def walk(
    hass: HomeAssistant,
    entry_id: str,
    *,
    tank: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
    draws: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
) -> Any:
    """Go through the four steps of the options flow and return the last result."""
    result = await hass.config_entries.options.async_init(entry_id)
    flow_id = result["flow_id"]
    for step, data in (
        ("init", TANK_FIELDS if tank is None else tank),
        ("sources", SOURCE_FIELDS if sources is None else sources),
        ("draws", draws or {}),
        ("learning", learning or {}),
    ):
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == step
        result = await hass.config_entries.options.async_configure(flow_id, data)
        if result["type"] is FlowResultType.FORM and result.get("errors"):
            return result
    return result


async def test_change_sensor_height(hass: HomeAssistant, freezer) -> None:
    """T_avg 44 C stays 44 C when the height goes from 50 % to 65 %; the next bound uses 65 %."""
    rig = await Rig.start(hass, freezer)
    entry = rig.entry
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, entry, "sensor", "tank_litres"),
            "tank_average": 44,
            "charged_temperature": 55,
        },
        blocking=True,
    )
    calibrator = entry.runtime_data.calibrator
    calibrator.values["other_hot_share"] = 0.22
    calibrator.sources["other_hot_share"] = "learned"
    state = calibrator.to_dict()
    old = entry.runtime_data

    result = await walk(
        hass, entry.entry_id, tank={**TANK_FIELDS, CONF_SENSOR_HEIGHT: 65}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    new = entry.runtime_data
    assert new is not old
    assert new.model.options.sensor_height == pytest.approx(0.65)
    assert new.model.t_avg == pytest.approx(44.0, abs=0.01)
    assert new.model.t_ch == pytest.approx(55.0, abs=0.01)
    assert new.calibrator.to_dict() == state
    assert rig.read("sensor", "other_hot_share") == "0.22"

    # The sensor still reads the hot layer, so the bound is a lower one: with the sensor at
    # 65 % the cold layer may reach 0.65 - 0.175 of the tank before the sensor falls. A
    # tank average of 30 C is raised to that bound, not to the bound of a 50 % sensor.
    t_cold = new.model.t_cold
    bound_65 = 55.0 - (0.65 - 0.35 / 2) * (55.0 - t_cold)
    bound_50 = 55.0 - (0.50 - 0.35 / 2) * (55.0 - t_cold)
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, entry, "sensor", "tank_litres"),
            "tank_average": 30,
        },
        blocking=True,
    )
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert bound_65 < bound_50 - 4
    assert new.model.t_avg == pytest.approx(bound_65, abs=0.1)


async def test_every_tuning_value_is_in_the_options_with_its_default(
    hass: HomeAssistant,
) -> None:
    """Saving the flow untouched stores every tuning value at its default from const.py."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(hass, entry.entry_id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = entry.options
    for tuning in (*SHAPE_TUNING, *DRAW_TUNING):
        assert options[tuning.key] == tuning.default, tuning.key
    assert options[CONF_HISTORY_DAYS] == 30
    config = TankConfig.from_options(options)
    assert config.options.sensor_height == 0.5
    assert config.options.thermocline_width == pytest.approx(0.35)
    assert config.locks == frozenset()


async def test_every_tuning_value_can_be_changed(hass: HomeAssistant) -> None:
    """A changed tuning value reaches the model."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(
        hass,
        entry.entry_id,
        tank={**TANK_FIELDS, "mix_temperature": 40.0, "thermocline_width": 30},
        draws={"session_gap": 30.0, "long_draw_minutes": 4.0},
        learning={CONF_HISTORY_DAYS: 14},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = entry.runtime_data.model.options
    assert options.mix_temperature == 40.0
    assert options.thermocline_width == pytest.approx(0.30)
    assert options.session_gap == 30.0
    assert options.long_draw_minutes == 4.0
    assert entry.runtime_data.config.history_days == 14


async def test_locks_are_stored_and_used(hass: HomeAssistant) -> None:
    """A lock keeps the option value of a learned parameter."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(
        hass,
        entry.entry_id,
        draws={"other_hot_share": 0.25},
        learning={CONF_LOCKS: ["other_hot_share", "usable_fraction"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    calibrator = entry.runtime_data.calibrator
    assert calibrator.locks == {"other_hot_share", "usable_fraction"}
    assert calibrator.source_of("other_hot_share") == "locked"
    assert calibrator.value_of("other_hot_share") == 0.25
    assert entry.runtime_data.model.options.other_hot_share == 0.25


async def test_an_unknown_lock_is_refused(hass: HomeAssistant) -> None:
    """Only the learned parameters can be locked."""
    set_sources(hass)
    entry = await setup_entry(hass)
    with pytest.raises(InvalidData):
        await walk(hass, entry.entry_id, learning={CONF_LOCKS: ["volume"]})


@pytest.mark.parametrize("days", [0, 31])
async def test_history_days_out_of_range(hass: HomeAssistant, days: int) -> None:
    """The history days are 1-30."""
    set_sources(hass)
    entry = await setup_entry(hass)
    with pytest.raises(InvalidData):
        await walk(hass, entry.entry_id, learning={CONF_HISTORY_DAYS: days})


async def test_clearing_an_optional_source_removes_it(hass: HomeAssistant) -> None:
    """A source that the user clears is no longer in the options or in the model."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(hass, entry.entry_id, sources={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert CONF_HUMIDITY_SENSORS not in entry.options
    assert CONF_FLOW_SENSOR not in entry.options
    assert entry.runtime_data.config.sources.humidity_sensors == ()
    assert not entry.runtime_data.config.sources.flow_return


async def test_adding_a_source(hass: HomeAssistant) -> None:
    """A cold water sensor can be added in the options."""
    set_sources(hass)
    hass.states.async_set(COLD, "11.0", {"unit_of_measurement": "°C"})
    entry = await setup_entry(hass)
    result = await walk(
        hass, entry.entry_id, sources={**SOURCE_FIELDS, CONF_COLD_SENSOR: COLD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.config.sources.cold_sensor
    assert entry.runtime_data.model.t_cold == 11.0


async def test_add_an_ambient_sensor(hass: HomeAssistant, hass_storage) -> None:
    """T_avg 52 C stays 52 C when an ambient sensor is added, and a recalibration runs."""
    set_sources(hass)
    hass.states.async_set(AMBIENT, "19.5", {"unit_of_measurement": "°C"})
    entry = await setup_fitted_entry(hass, hass_storage)
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, entry, "sensor", "tank_litres"),
            "tank_average": 52,
            "charged_temperature": 55,
        },
        blocking=True,
    )
    hass.config.components.add("recorder")
    now = dt_util.utcnow()
    read = AsyncMock(return_value=History(now - timedelta(days=30), now, []))
    with patch(
        "custom_components.hot_water_tank_estimator.estimator.async_read_history", read
    ):
        result = await walk(
            hass,
            entry.entry_id,
            sources={**SOURCE_FIELDS, CONF_AMBIENT_SENSOR: AMBIENT},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    # The recalibration read the history of the configured sources, the ambient sensor's too.
    read.assert_awaited_once()
    _, config, start, end = read.await_args.args
    assert config.routes[AMBIENT] == ("ambient_temperature",)
    assert end - start == timedelta(days=config.history_days)
    assert entry.runtime_data.payload()["ambient_fit"] == AMBIENT
    model = entry.runtime_data.model
    assert entry.runtime_data.config.sources.ambient_sensor
    assert model.ambient_temperature(dt_util.utcnow()) == 19.5
    assert model.t_avg == pytest.approx(52.0, abs=0.01)


async def test_a_save_without_an_ambient_change_starts_no_recalibration(
    hass: HomeAssistant, hass_storage
) -> None:
    """Saving the options with the same ambient sensor, or none, runs no fit."""
    set_sources(hass)
    hass.states.async_set(AMBIENT, "19.5", {"unit_of_measurement": "°C"})
    entry = await setup_fitted_entry(
        hass, hass_storage, {**FULL_OPTIONS, CONF_AMBIENT_SENSOR: AMBIENT}, AMBIENT
    )
    with patch.object(
        TankEstimator, "async_setup_fit", new=AsyncMock(return_value=None)
    ) as fit:
        await walk(
            hass,
            entry.entry_id,
            sources={**SOURCE_FIELDS, CONF_AMBIENT_SENSOR: AMBIENT},
        )
        await hass.async_block_till_done()
        fit.assert_not_awaited()
    hass_storage.clear()
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    without = await setup_fitted_entry(hass, hass_storage)
    with patch.object(
        TankEstimator, "async_setup_fit", new=AsyncMock(return_value=None)
    ) as fit:
        await walk(hass, without.entry_id)
        await hass.async_block_till_done()
        fit.assert_not_awaited()


@pytest.mark.parametrize("change", ["remove", "replace"])
async def test_removing_or_replacing_the_ambient_sensor_recalibrates(
    hass: HomeAssistant, hass_storage, change: str
) -> None:
    """Clearing the ambient sensor or choosing another one starts a recalibration."""
    set_sources(hass)
    hass.states.async_set(AMBIENT, "19.5", {"unit_of_measurement": "°C"})
    entry = await setup_fitted_entry(
        hass, hass_storage, {**FULL_OPTIONS, CONF_AMBIENT_SENSOR: AMBIENT}, AMBIENT
    )
    hass.states.async_set("sensor.other_ambient", "18", {"unit_of_measurement": "°C"})
    new = {} if change == "remove" else {CONF_AMBIENT_SENSOR: "sensor.other_ambient"}
    with patch.object(
        TankEstimator, "async_setup_fit", new=AsyncMock(return_value=None)
    ) as fit:
        await walk(hass, entry.entry_id, sources={**SOURCE_FIELDS, **new})
        await hass.async_block_till_done()
        fit.assert_awaited_once_with()
        model = entry.runtime_data.model
        expected = 20.0 if change == "remove" else 18.0
        assert model.ambient_temperature(dt_util.utcnow()) == expected


async def test_the_ambient_fallback_is_a_tuning_value(hass: HomeAssistant) -> None:
    """The fallback time is saved in hours and reaches the model."""
    set_sources(hass)
    entry = await setup_entry(hass)
    shape = {t.key: t.default for t in SHAPE_TUNING} | {"ambient_fallback": 6.0}
    result = await walk(hass, entry.entry_id, tank={CONF_SENSOR_HEIGHT: 50, **shape})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.model.options.ambient_fallback == 6.0
    for bad in (-1, 25):
        with pytest.raises(InvalidData):
            await walk(
                hass,
                entry.entry_id,
                tank={CONF_SENSOR_HEIGHT: 50, **shape, "ambient_fallback": bad},
            )


async def test_options_validation(hass: HomeAssistant) -> None:
    """The options flow checks the height and the flow and return pair."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(
        hass, entry.entry_id, tank={**TANK_FIELDS, CONF_SENSOR_HEIGHT: 90}
    )
    assert result["step_id"] == "init"
    assert result["errors"] == {CONF_SENSOR_HEIGHT: "height_out_of_range"}

    result = await walk(hass, entry.entry_id, sources={CONF_FLOW_SENSOR: FLOW})
    assert result["step_id"] == "sources"
    assert result["errors"] == {"base": "flow_return_pair"}


async def test_the_options_flow_leaves_the_reconfigure_fields_out(
    hass: HomeAssistant,
) -> None:
    """The volume, tank sensor, water meter and heat inputs are not in the options forms and stay."""
    set_sources(hass)
    entry = await setup_entry(hass)
    before = dict(entry.options)
    moved = {
        CONF_VOLUME,
        CONF_TANK_SENSOR,
        CONF_WATER_METER,
        CONF_ENERGY_COUNTER,
        "power_sensor",
        "heating_active",
    }
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    seen: set[str] = set()
    for step, data in (
        ("init", TANK_FIELDS),
        ("sources", SOURCE_FIELDS),
        ("draws", {}),
        ("learning", {}),
    ):
        assert result["step_id"] == step
        seen |= {marker.schema for marker in result["data_schema"].schema}
        result = await hass.config_entries.options.async_configure(flow_id, data)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not seen & moved
    await hass.async_block_till_done()
    for key in moved:
        assert entry.options.get(key) == before.get(key), key


async def test_the_shower_times_keep_the_state(hass: HomeAssistant, freezer) -> None:
    """Saving the shower end time and the next shower time keeps T_avg, T_ch and the calibration."""
    rig = await Rig.start(hass, freezer)
    entry = rig.entry
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, entry, "sensor", "tank_litres"),
            "tank_average": 44,
            "charged_temperature": 55,
        },
        blocking=True,
    )
    calibrator = entry.runtime_data.calibrator
    calibrator.values["other_hot_share"] = 0.22
    calibrator.sources["other_hot_share"] = "learned"
    state = calibrator.to_dict()

    result = await walk(
        hass,
        entry.entry_id,
        draws={"shower_end_minutes": 8.5, "next_shower_minutes": 3.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    new = entry.runtime_data
    assert new.model.options.shower_end_minutes == 8.5
    assert new.model.options.next_shower_minutes == 3.0
    assert new.model.t_avg == pytest.approx(44.0, abs=0.01)
    assert new.model.t_ch == pytest.approx(55.0, abs=0.01)
    assert new.calibrator.to_dict() == state


@pytest.mark.parametrize(
    ("end", "gap", "accepted"),
    [
        (2.0, 120.0, False),
        (2.0, 600.0, False),
        (2.5, 150.0, False),
        (2.0, 115.0, True),
        (5.0, 60.0, True),
    ],
)
async def test_the_shower_end_time_must_be_longer_than_the_session_gap(
    hass: HomeAssistant, end: float, gap: float, accepted: bool
) -> None:
    """A shower end time at or below the session gap is refused with an error on the field."""
    set_sources(hass)
    entry = await setup_entry(hass)
    draws = {"shower_end_minutes": end, "session_gap": gap}
    result = await walk(hass, entry.entry_id, draws=draws)
    if accepted:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["step_id"] == "draws"
        assert result["errors"] == {"shower_end_minutes": "shower_end_not_after_gap"}


async def test_shower_end_time_not_after_the_session_gap(hass: HomeAssistant) -> None:
    """Scenario "Shower end time not after the session gap": 2 min and 120 s show an error and save nothing."""
    set_sources(hass)
    entry = await setup_entry(hass)
    before = dict(entry.options)
    result = await walk(
        hass,
        entry.entry_id,
        draws={"shower_end_minutes": 2.0, "session_gap": 120.0},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"shower_end_minutes": "shower_end_not_after_gap"}
    assert dict(entry.options) == before


async def test_option_saved(hass: HomeAssistant) -> None:
    """Integration-setup scenario "Option saved": a saved shower end time of 7.5 shows after the reload."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(hass, entry.entry_id, draws={"shower_end_minutes": 7.5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert float(value(hass, entry, "sensor", "shower_end_time")) == 7.5
    assert float(value(hass, entry, "sensor", "next_shower_time")) == 5.0
