"""Tests for the config flow: the steps, the validation and the defaults of a fresh entry."""

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.hot_water_tank_estimator.const import (
    CONF_AMBIENT_SENSOR,
    CONF_COLD_SENSOR,
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_HUMIDITY_SENSORS,
    CONF_POWER_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_VOLUME,
    CONF_WATER_METER,
    DOMAIN,
)
from custom_components.hot_water_tank_estimator.estimator import TankConfig
from custom_components.hot_water_tank_estimator.model import ModelOptions
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from .common import (
    AMBIENT,
    COLD,
    ENERGY,
    FLOW,
    FULL_OPTIONS,
    HEATING,
    HUMIDITY,
    METER,
    POWER,
    RETURN,
    TANK,
    set_sources,
    setup_entry,
)

TANK_STEP = {
    "name": "Upstairs",
    CONF_VOLUME: 281,
    CONF_TANK_SENSOR: TANK,
    CONF_SENSOR_HEIGHT: 50,
}
STRINGS = json.loads(
    (
        Path(__file__).parent.parent
        / "custom_components"
        / "hot_water_tank_estimator"
        / "strings.json"
    ).read_text("utf-8")
)


async def start(hass: HomeAssistant) -> str:
    """Start a flow and return its ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result["flow_id"]


async def to_step(hass: HomeAssistant, step: str, tank: dict[str, Any] | None = None):
    """Walk a new flow up to a step (water_meter, heat, detection or temperatures)."""
    set_sources(hass)
    flow_id = await start(hass)
    steps = ["water_meter", "heat", "detection", "temperatures"]
    inputs = {
        "user": tank or TANK_STEP,
        "water_meter": {CONF_WATER_METER: METER},
        "heat": {CONF_ENERGY_COUNTER: ENERGY},
        "detection": {},
    }
    result = await hass.config_entries.flow.async_configure(flow_id, inputs["user"])
    for name in steps[: steps.index(step)]:
        assert result["step_id"] == name
        result = await hass.config_entries.flow.async_configure(flow_id, inputs[name])
    assert result["step_id"] == step
    return flow_id


async def test_full_flow_creates_an_entry(hass: HomeAssistant) -> None:
    """All five steps create one entry with the sources in its options."""
    set_sources(hass)
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, TANK_STEP)
    assert result["step_id"] == "water_meter"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_WATER_METER: METER}
    )
    assert result["step_id"] == "heat"
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ENERGY_COUNTER: ENERGY,
            CONF_HEATING_ACTIVE: HEATING,
            CONF_FLOW_SENSOR: FLOW,
            CONF_RETURN_SENSOR: RETURN,
        },
    )
    assert result["step_id"] == "detection"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_HUMIDITY_SENSORS: [HUMIDITY]}
    )
    assert result["step_id"] == "temperatures"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_COLD_SENSOR: COLD, CONF_AMBIENT_SENSOR: AMBIENT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Upstairs"
    assert result["options"] == {
        CONF_VOLUME: 281,
        CONF_TANK_SENSOR: TANK,
        CONF_SENSOR_HEIGHT: 50,
        CONF_WATER_METER: METER,
        CONF_ENERGY_COUNTER: ENERGY,
        CONF_HEATING_ACTIVE: HEATING,
        CONF_FLOW_SENSOR: FLOW,
        CONF_RETURN_SENSOR: RETURN,
        CONF_HUMIDITY_SENSORS: [HUMIDITY],
        CONF_COLD_SENSOR: COLD,
        CONF_AMBIENT_SENSOR: AMBIENT,
    }


async def test_a_minimal_entry_needs_only_the_required_sources(
    hass: HomeAssistant,
) -> None:
    """The tank, the meter and one heat input are enough."""
    flow_id = await to_step(hass, "temperatures")
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert CONF_COLD_SENSOR not in entries[0].options
    assert CONF_AMBIENT_SENSOR not in entries[0].options
    assert not TankConfig.from_options(entries[0].options).sources.ambient_sensor


async def test_fresh_entry_temperature_and_shape_defaults(hass: HomeAssistant) -> None:
    """A fresh entry runs with the default temperatures and tank shape."""
    flow_id = await to_step(hass, "temperatures")
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    options = TankConfig.from_options(result["options"]).options
    assert options.sensor_height == 0.5
    assert options.thermocline_width == 0.35
    assert options.usable_fraction == 0.85
    assert options.mix_temperature == 38
    assert options.max_temperature == 95
    assert options.sensor_tolerance == 1.5
    assert options.sensor_margin == 2
    assert options.ambient_temperature == 20
    assert options.ambient_fallback == 3
    assert options.cold_mean == 12.5
    assert options.cold_amplitude == 5
    assert options.cold_coldest_day == 46


async def test_fresh_entry_draw_and_heat_defaults(hass: HomeAssistant) -> None:
    """A fresh entry runs with the default draw, loss and heat values."""
    flow_id = await to_step(hass, "temperatures")
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    options = TankConfig.from_options(result["options"]).options
    defaults = ModelOptions(volume=281.0)
    assert options == ModelOptions(volume=281.0)
    assert defaults.loss_coefficient == 0.004
    assert options.other_hot_share == 0.2
    assert options.startup_energy == 0
    assert options.shower_flow == 7.5
    assert options.humidity_rise == 6
    assert options.humidity_window == 60
    assert options.humidity_silence == 2
    assert options.shower_end_minutes == 5
    assert options.next_shower_minutes == 5
    assert options.long_draw_minutes == 0
    assert options.reclassify_window == 10
    assert options.session_gap == 60
    assert options.max_draw == 100
    assert options.power_threshold == 100
    assert options.outside_heat is False


@pytest.mark.parametrize("missing", [CONF_TANK_SENSOR, CONF_VOLUME, "name"])
async def test_required_fields_of_the_tank_step(
    hass: HomeAssistant, missing: str
) -> None:
    """The tank step does not submit without the tank sensor, the volume or a name."""
    flow_id = await start(hass)
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            flow_id, {k: v for k, v in TANK_STEP.items() if k != missing}
        )


async def test_the_water_meter_is_required(hass: HomeAssistant) -> None:
    """The water meter step does not submit without a meter."""
    flow_id = await to_step(hass, "water_meter")
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(flow_id, {})


@pytest.mark.parametrize(
    "heat",
    [{}, {CONF_FLOW_SENSOR: FLOW, CONF_RETURN_SENSOR: RETURN}],
)
async def test_no_heat_information(hass: HomeAssistant, heat: dict[str, Any]) -> None:
    """With no energy counter, power sensor or heating binary sensor the step shows an error."""
    flow_id = await to_step(hass, "heat")
    result = await hass.config_entries.flow.async_configure(flow_id, heat)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "heat"
    assert result["errors"] == {"base": "no_heat_source"}


@pytest.mark.parametrize(
    "heat",
    [
        {CONF_POWER_SENSOR: POWER, CONF_FLOW_SENSOR: FLOW},
        {CONF_HEATING_ACTIVE: HEATING, CONF_RETURN_SENSOR: RETURN},
    ],
)
async def test_only_one_of_flow_and_return(
    hass: HomeAssistant, heat: dict[str, Any]
) -> None:
    """A flow sensor without a return sensor, or the reverse, shows an error."""
    flow_id = await to_step(hass, "heat")
    result = await hass.config_entries.flow.async_configure(flow_id, heat)
    assert result["step_id"] == "heat"
    assert result["errors"] == {"base": "flow_return_pair"}


@pytest.mark.parametrize("heat_key", [CONF_POWER_SENSOR, CONF_HEATING_ACTIVE])
async def test_any_one_heat_input_is_enough(hass: HomeAssistant, heat_key: str) -> None:
    """A power sensor alone, or a heating binary sensor alone, is a heat input."""
    flow_id = await to_step(hass, "heat")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {heat_key: POWER if heat_key == CONF_POWER_SENSOR else HEATING}
    )
    assert result["step_id"] == "detection"


@pytest.mark.parametrize("unit", ["kW", "°C", None])
async def test_unsuitable_water_meter(hass: HomeAssistant, unit: str | None) -> None:
    """A meter without a volume unit shows an error that names the accepted units."""
    flow_id = await to_step(hass, "water_meter")
    attributes = {} if unit is None else {"unit_of_measurement": unit}
    hass.states.async_set(METER, "5.0", attributes)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_WATER_METER: METER}
    )
    assert result["step_id"] == "water_meter"
    assert result["errors"] == {CONF_WATER_METER: "water_meter_unit"}
    message = STRINGS["config"]["error"]["water_meter_unit"]
    for accepted in ("L", "m3", "gal", "ft3"):
        assert accepted in message


@pytest.mark.parametrize("unit", ["L", "m³", "gal", "ft³"])
async def test_volume_units_of_the_water_meter(hass: HomeAssistant, unit: str) -> None:
    """Litres, cubic metres, gallons and cubic feet are accepted."""
    flow_id = await to_step(hass, "water_meter")
    hass.states.async_set(METER, "5.0", {"unit_of_measurement": unit})
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_WATER_METER: METER}
    )
    assert result["step_id"] == "heat"


async def test_an_unavailable_water_meter_is_accepted(hass: HomeAssistant) -> None:
    """A meter that is offline has no unit to check yet."""
    flow_id = await to_step(hass, "water_meter")
    hass.states.async_set(METER, "unavailable")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_WATER_METER: METER}
    )
    assert result["step_id"] == "heat"


@pytest.mark.parametrize("height", [90, 10, 19.9, 80.1])
async def test_sensor_height_out_of_range(hass: HomeAssistant, height: float) -> None:
    """A sensor height outside 20-80 % shows an error."""
    set_sources(hass)
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**TANK_STEP, CONF_SENSOR_HEIGHT: height}
    )
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_SENSOR_HEIGHT: "height_out_of_range"}
    assert "20-80" in STRINGS["config"]["error"]["height_out_of_range"]


@pytest.mark.parametrize("height", [20, 80])
async def test_sensor_height_limits_are_accepted(
    hass: HomeAssistant, height: float
) -> None:
    """20 % and 80 % are inside the range."""
    set_sources(hass)
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**TANK_STEP, CONF_SENSOR_HEIGHT: height}
    )
    assert result["step_id"] == "water_meter"


@pytest.mark.parametrize("volume", [19, 2001, 0])
async def test_volume_out_of_range(hass: HomeAssistant, volume: float) -> None:
    """A volume outside 20-2000 L shows an error."""
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**TANK_STEP, CONF_VOLUME: volume}
    )
    assert result["errors"] == {CONF_VOLUME: "volume_out_of_range"}


async def test_two_tanks(hass: HomeAssistant) -> None:
    """Two tanks with their own sensors make two entries."""
    for name, sensor in (("Upstairs", TANK), ("Downstairs", "sensor.cellar_tank")):
        set_sources(hass)
        hass.states.async_set(sensor, "50.0", {"unit_of_measurement": "°C"})
        flow_id = await start(hass)
        await hass.config_entries.flow.async_configure(
            flow_id, {**TANK_STEP, "name": name, CONF_TANK_SENSOR: sensor}
        )
        await hass.config_entries.flow.async_configure(
            flow_id, {CONF_WATER_METER: METER}
        )
        await hass.config_entries.flow.async_configure(
            flow_id, {CONF_ENERGY_COUNTER: ENERGY}
        )
        await hass.config_entries.flow.async_configure(flow_id, {})
        result = await hass.config_entries.flow.async_configure(flow_id, {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {e.title for e in hass.config_entries.async_entries(DOMAIN)} == {
        "Upstairs",
        "Downstairs",
    }


async def test_the_same_tank_sensor_twice_is_aborted(hass: HomeAssistant) -> None:
    """A tank sensor that another entry uses aborts the flow."""
    flow_id = await to_step(hass, "temperatures")
    await hass.config_entries.flow.async_configure(flow_id, {})
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, TANK_STEP)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_existing_entry_after_the_update(hass: HomeAssistant) -> None:
    """An entry saved before the shower end and next shower times and the humidity silence time uses their defaults and keeps its other values."""
    options = {**FULL_OPTIONS, "session_gap": 30.0, "long_draw_minutes": 4.0}
    assert "shower_end_minutes" not in options
    assert "next_shower_minutes" not in options
    set_sources(hass)
    entry = await setup_entry(hass, options)
    model_options = entry.runtime_data.model.options
    assert model_options.shower_end_minutes == 5
    assert model_options.next_shower_minutes == 5
    assert model_options.outside_heat is False
    assert model_options.humidity_silence == 2
    assert model_options.session_gap == 30.0
    assert model_options.long_draw_minutes == 4.0
    assert model_options.humidity_rise == 6
