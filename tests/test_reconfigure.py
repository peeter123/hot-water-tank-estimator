"""Tests for the reconfigure step: it changes the tank and the sources and keeps the entry and its state."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.hot_water_tank_estimator.const import (
    CONF_AMBIENT_SENSOR,
    CONF_COLD_SENSOR,
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_HISTORY_DAYS,
    CONF_HUMIDITY_SENSORS,
    CONF_LOCKS,
    CONF_POWER_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_VOLUME,
    CONF_WATER_METER,
    DOMAIN,
)
from custom_components.hot_water_tank_estimator.estimator import TankEstimator
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .common import (
    AMBIENT,
    COLD,
    FULL_OPTIONS,
    METER,
    POWER,
    TANK,
    entity_id,
    set_sources,
    setup_entry,
    setup_fitted_entry,
    value,
)
from .test_calibration import make_closure

OTHER_TANK = "sensor.cellar_tank"
NEW_METER = "sensor.new_water_meter"
FORM = {
    CONF_VOLUME: 300,
    CONF_TANK_SENSOR: TANK,
    CONF_SENSOR_HEIGHT: 60,
    CONF_WATER_METER: METER,
    CONF_POWER_SENSOR: POWER,
    CONF_COLD_SENSOR: COLD,
}


async def start(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Open the reconfigure form of an entry."""
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result


async def test_replace_the_water_meter(hass: HomeAssistant) -> None:
    """A new water meter reloads the entry; the temperatures, the lock and the calibration stay."""
    set_sources(hass)
    hass.states.async_set(
        NEW_METER, "50.0", {"unit_of_measurement": "m³", "device_class": "water"}
    )
    options = {
        **FULL_OPTIONS,
        "usable_fraction": 0.7,
        CONF_LOCKS: ["usable_fraction"],
        CONF_HISTORY_DAYS: 14,
    }
    entry = await setup_entry(hass, options)
    tank_litres = entity_id(hass, entry, "sensor", "tank_litres")
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": tank_litres,
            "tank_average": 50,
            "charged_temperature": 55,
        },
        blocking=True,
    )
    entry.runtime_data.calibrator.closures.append(make_closure())
    old = entry.runtime_data

    result = await start(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**FORM, CONF_WATER_METER: NEW_METER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    new = entry.runtime_data
    assert new is not old
    assert entry.options == {
        **FORM,
        CONF_WATER_METER: NEW_METER,
        "usable_fraction": 0.7,
        CONF_LOCKS: ["usable_fraction"],
        CONF_HISTORY_DAYS: 14,
    }
    for gone in (
        CONF_ENERGY_COUNTER,
        CONF_HEATING_ACTIVE,
        CONF_FLOW_SENSOR,
        CONF_RETURN_SENSOR,
        CONF_HUMIDITY_SENSORS,
    ):
        assert gone not in entry.options
    assert NEW_METER in new.config.routes
    assert METER not in new.config.routes
    assert new.model.t_avg == pytest.approx(50.0, abs=0.01)
    assert new.model.t_ch == pytest.approx(55.0, abs=0.01)
    assert new.calibrator.sample_count == 1
    assert new.calibrator.locks == {"usable_fraction"}
    assert new.config.history_days == 14
    assert value(hass, entry, "sensor", "calibration_samples") == "1"
    assert entity_id(hass, entry, "sensor", "tank_litres") == tank_litres
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize(
    ("before", "after", "runs"),
    [
        (None, AMBIENT, True),
        (AMBIENT, None, True),
        (AMBIENT, "sensor.other_ambient", True),
        (AMBIENT, AMBIENT, False),
        (None, None, False),
    ],
)
async def test_reconfigure_recalibrates_only_when_the_ambient_sensor_changes(
    hass: HomeAssistant,
    hass_storage,
    before: str | None,
    after: str | None,
    runs: bool,
) -> None:
    """Adding, removing or replacing the ambient sensor starts a fit after the reload."""
    set_sources(hass)
    for sensor in (AMBIENT, "sensor.other_ambient"):
        hass.states.async_set(sensor, "19.5", {"unit_of_measurement": "°C"})
    options = {**FULL_OPTIONS} | ({CONF_AMBIENT_SENSOR: before} if before else {})
    entry = await setup_fitted_entry(hass, hass_storage, options, before)
    result = await start(hass, entry)
    form = {**FORM} | ({CONF_AMBIENT_SENSOR: after} if after else {})
    with patch.object(
        TankEstimator, "async_setup_fit", new=AsyncMock(return_value=None)
    ) as fit:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], form)
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        assert (fit.await_count == 1) is runs
    assert entry.options.get(CONF_AMBIENT_SENSOR) == after


async def test_ambient_sensor_in_reconfigure(hass: HomeAssistant, hass_storage) -> None:
    """T_avg 52 C, an ambient sensor added in reconfigure: reload, T_avg stays 52 C, a fit runs."""
    set_sources(hass)
    hass.states.async_set(AMBIENT, "19.5", {"unit_of_measurement": "°C"})
    entry = await setup_fitted_entry(
        hass, hass_storage, {**FULL_OPTIONS, CONF_HISTORY_DAYS: 14}, None
    )
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
    old = entry.runtime_data
    result = await start(hass, entry)
    with patch.object(
        TankEstimator, "async_setup_fit", new=AsyncMock(return_value=None)
    ) as fit:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**FORM, CONF_AMBIENT_SENSOR: AMBIENT}
        )
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        assert fit.await_count == 1
    new = entry.runtime_data
    assert new is not old
    assert entry.options[CONF_AMBIENT_SENSOR] == AMBIENT
    assert new.model.t_avg == pytest.approx(52.0, abs=0.01)
    assert new.config.history_days == 14


async def test_reconfigure_can_keep_the_same_tank_sensor(hass: HomeAssistant) -> None:
    """The entry's own tank sensor is not a duplicate."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await start(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_aborts_for_a_tank_sensor_of_another_entry(
    hass: HomeAssistant,
) -> None:
    """A tank sensor that belongs to another entry aborts the flow and changes nothing."""
    set_sources(hass)
    hass.states.async_set(OTHER_TANK, "50.0", {"unit_of_measurement": "°C"})
    entry = await setup_entry(hass)
    await setup_entry(
        hass, {**FULL_OPTIONS, CONF_TANK_SENSOR: OTHER_TANK}, title="Other"
    )
    result = await start(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**FORM, CONF_TANK_SENSOR: OTHER_TANK}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.options[CONF_TANK_SENSOR] == TANK


@pytest.mark.parametrize(
    ("change", "errors"),
    [
        ({CONF_VOLUME: 10}, {CONF_VOLUME: "volume_out_of_range"}),
        ({CONF_SENSOR_HEIGHT: 90}, {CONF_SENSOR_HEIGHT: "height_out_of_range"}),
        ({CONF_POWER_SENSOR: None}, {"base": "no_heat_source"}),
        ({CONF_FLOW_SENSOR: "sensor.flow"}, {"base": "flow_return_pair"}),
    ],
)
async def test_reconfigure_validates_like_the_setup(
    hass: HomeAssistant, change: dict[str, Any], errors: dict[str, str]
) -> None:
    """The setup steps' errors show again, and the form keeps what was entered."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await start(hass, entry)
    user_input = {k: v for k, v in {**FORM, **change}.items() if v is not None}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert entry.options == FULL_OPTIONS


async def test_reconfigure_rejects_a_meter_without_a_volume_unit(
    hass: HomeAssistant,
) -> None:
    """A water meter with another unit shows the error of the setup step."""
    set_sources(hass)
    entry = await setup_entry(hass)
    hass.states.async_set(METER, "5.0", {"unit_of_measurement": "kW"})
    result = await start(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["errors"] == {CONF_WATER_METER: "water_meter_unit"}


async def test_the_form_is_filled_from_the_entry(hass: HomeAssistant) -> None:
    """The first form shows the entry's current values as suggestions."""
    set_sources(hass)
    entry = await setup_entry(hass, {**FULL_OPTIONS, CONF_SENSOR_HEIGHT: 63.0})
    result = await start(hass, entry)
    suggested = {
        marker.schema: marker.description["suggested_value"]
        for marker in result["data_schema"].schema
        if marker.description
    }
    assert suggested[CONF_SENSOR_HEIGHT] == 63.0
    assert suggested[CONF_VOLUME] == FULL_OPTIONS[CONF_VOLUME]
    assert suggested[CONF_TANK_SENSOR] == TANK
