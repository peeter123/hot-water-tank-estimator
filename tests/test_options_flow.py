"""Tests for the options flow: every value, the validation, and a reload that keeps the state (task 5.2)."""

from datetime import timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hot_water_tank_estimator.config_flow import (
    DRAW_TUNING,
    SHAPE_TUNING,
)
from custom_components.hot_water_tank_estimator.const import (
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
from custom_components.hot_water_tank_estimator.estimator import TankConfig
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from .common import (
    COLD,
    ENERGY,
    FLOW,
    HUMIDITY,
    METER,
    POWER,
    RETURN,
    TANK,
    Rig,
    entity_id,
    set_sources,
    setup_entry,
)

TANK_FIELDS = {CONF_VOLUME: 281, CONF_TANK_SENSOR: TANK, CONF_SENSOR_HEIGHT: 50}
SOURCE_FIELDS = {
    CONF_WATER_METER: METER,
    CONF_ENERGY_COUNTER: ENERGY,
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
        ("init", tank or TANK_FIELDS),
        ("sources", sources or SOURCE_FIELDS),
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
        draws={"shower_flow": 9.0, "session_gap": 30.0, "long_draw_minutes": 4.0},
        learning={CONF_HISTORY_DAYS: 14},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = entry.runtime_data.model.options
    assert options.mix_temperature == 40.0
    assert options.thermocline_width == pytest.approx(0.30)
    assert options.shower_flow == 9.0
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
    sources = {
        CONF_WATER_METER: METER,
        CONF_ENERGY_COUNTER: ENERGY,
    }
    result = await walk(hass, entry.entry_id, sources=sources)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert CONF_HUMIDITY_SENSORS not in entry.options
    assert CONF_FLOW_SENSOR not in entry.options
    assert entry.runtime_data.config.sources.humidity_sensors == ()
    assert not entry.runtime_data.config.sources.flow_return


async def test_adding_a_source(hass: HomeAssistant) -> None:
    """A cold water sensor and a power sensor can be added in the options."""
    set_sources(hass)
    hass.states.async_set(COLD, "11.0", {"unit_of_measurement": "°C"})
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_entry(hass)
    result = await walk(
        hass,
        entry.entry_id,
        sources={**SOURCE_FIELDS, CONF_COLD_SENSOR: COLD, "power_sensor": POWER},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    sources = entry.runtime_data.config.sources
    assert sources.cold_sensor
    assert sources.power
    assert entry.runtime_data.model.t_cold == 11.0


async def test_options_validation(hass: HomeAssistant) -> None:
    """The options flow checks the height, the heat input and the flow and return pair."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await walk(
        hass, entry.entry_id, tank={**TANK_FIELDS, CONF_SENSOR_HEIGHT: 90}
    )
    assert result["step_id"] == "init"
    assert result["errors"] == {CONF_SENSOR_HEIGHT: "height_out_of_range"}

    result = await walk(
        hass, entry.entry_id, sources={CONF_WATER_METER: METER, CONF_FLOW_SENSOR: FLOW}
    )
    assert result["step_id"] == "sources"
    assert result["errors"] == {"base": "flow_return_pair"}

    result = await walk(hass, entry.entry_id, sources={CONF_WATER_METER: METER})
    assert result["errors"] == {"base": "no_heat_source"}

    hass.states.async_set(METER, "1.0", {"unit_of_measurement": "kW"})
    result = await walk(hass, entry.entry_id, sources=SOURCE_FIELDS)
    assert result["errors"] == {CONF_WATER_METER: "water_meter_unit"}
