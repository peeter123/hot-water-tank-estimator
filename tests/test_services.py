"""Tests for the actions set_tank_state and recalibrate (task 5.6).

The recalibrate scenarios that need recorder history are in `test_calibration_runtime.py`.
"""

import probatio
import pytest

from custom_components.hot_water_tank_estimator.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from .common import METER, TANK, Rig, entity_id, set_sources, setup_entry


def target(hass: HomeAssistant, rig: Rig) -> dict[str, str]:
    """Return the entity target of the rig's tank."""
    return {"entity_id": entity_id(hass, rig.entry, "sensor", "tank_litres")}


async def test_charge_by_hand(hass: HomeAssistant, freezer) -> None:
    """With no temperatures the tank is charged to the tank sensor's reading."""
    rig = await Rig.start(hass, freezer, states={TANK: "55.0"})
    await rig.set(METER, "100.020", after=30)
    assert rig.read("sensor", "tank_average") != rig.read(
        "sensor", "charged_temperature"
    )
    await rig.set(TANK, "52.0", after=30)
    await hass.services.async_call(
        DOMAIN, "set_tank_state", target(hass, rig), blocking=True
    )
    assert rig.read("sensor", "tank_average") == "52.0"
    assert rig.read("sensor", "charged_temperature") == "52.0"
    assert rig.read("sensor", "percent_charged") == "100"


async def test_set_the_average_only(hass: HomeAssistant, freezer) -> None:
    """Only a tank average: T_avg becomes 30 C and T_ch stays 55 C."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {**target(hass, rig), "tank_average": 40, "charged_temperature": 55},
        blocking=True,
    )
    assert rig.read("sensor", "charged_temperature") == "55.0"
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {**target(hass, rig), "tank_average": 30},
        blocking=True,
    )
    assert rig.read("sensor", "tank_average") == "30.0"
    assert rig.read("sensor", "charged_temperature") == "55.0"


async def test_the_bounds_apply(hass: HomeAssistant, freezer) -> None:
    """A tank average above the charged temperature is brought back to it."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {**target(hass, rig), "tank_average": 80, "charged_temperature": 55},
        blocking=True,
    )
    assert rig.read("sensor", "tank_average") == "55.0"
    assert rig.read("sensor", "charged_temperature") == "55.0"


async def test_no_temperatures_and_the_sensor_is_unavailable(
    hass: HomeAssistant, freezer
) -> None:
    """The action fails with an error and the state is unchanged."""
    rig = await Rig.start(hass, freezer)
    await rig.set(METER, "100.020", after=30)
    average = rig.read("sensor", "tank_average")
    charged = rig.read("sensor", "charged_temperature")
    await rig.set(TANK, "unavailable", after=5)
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN, "set_tank_state", target(hass, rig), blocking=True
        )
    assert error.value.translation_key == "tank_sensor_unavailable"
    assert rig.read("sensor", "tank_average") == average
    assert rig.read("sensor", "charged_temperature") == charged


async def test_the_model_refuses_when_the_sensor_is_unavailable(
    hass: HomeAssistant, freezer
) -> None:
    """The estimator itself also refuses, and leaves the temperatures as they are."""
    rig = await Rig.start(hass, freezer)
    await rig.set(TANK, "unavailable", after=5)
    estimator = rig.entry.runtime_data
    before = (estimator.model.t_avg, estimator.model.t_ch)
    with pytest.raises(ValueError, match="unavailable"):
        estimator.set_state(None, None)
    assert (estimator.model.t_avg, estimator.model.t_ch) == before


async def test_a_device_can_be_the_target(hass: HomeAssistant, freezer) -> None:
    """The action also takes the device of the tank."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    device = dr.async_entries_for_config_entry(dr.async_get(hass), rig.entry.entry_id)[
        0
    ]
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {"device_id": device.id, "tank_average": 33, "charged_temperature": 33},
        blocking=True,
    )
    assert rig.read("sensor", "tank_average") == "33.0"


async def test_two_tanks_only_the_targeted_one_changes(
    hass: HomeAssistant, freezer
) -> None:
    """The target picks the tank."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    hass.states.async_set("sensor.cellar_tank", "48.0", {"unit_of_measurement": "°C"})
    other = await setup_entry(
        hass,
        {**rig.entry.options, "tank_sensor": "sensor.cellar_tank"},
        "Cellar",
    )
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {**target(hass, rig), "tank_average": 33, "charged_temperature": 33},
        blocking=True,
    )
    assert rig.read("sensor", "tank_average") == "33.0"
    assert other.runtime_data.model.t_avg == 48.0


async def test_no_tank_targeted(hass: HomeAssistant, freezer) -> None:
    """A target that is not a tank is an error."""
    await Rig.start(hass, freezer)
    hass.states.async_set("light.kitchen", "on")
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            "set_tank_state",
            {"entity_id": "light.kitchen"},
            blocking=True,
        )
    assert error.value.translation_key == "no_tank_targeted"


async def test_recalibrate_without_the_recorder(hass: HomeAssistant, freezer) -> None:
    """Without recorder history the action fails with an error and changes nothing."""
    rig = await Rig.start(hass, freezer)
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN, "recalibrate", target(hass, rig), blocking=True
        )
    assert error.value.translation_key == "no_history"


@pytest.mark.parametrize("days", [0, 31])
async def test_recalibrate_days_are_1_to_30(
    hass: HomeAssistant, freezer, days: int
) -> None:
    """The number of days is checked."""
    rig = await Rig.start(hass, freezer)
    with pytest.raises(probatio.Invalid):
        await hass.services.async_call(
            DOMAIN, "recalibrate", {**target(hass, rig), "days": days}, blocking=True
        )


async def test_the_actions_are_registered_without_an_entry(hass: HomeAssistant) -> None:
    """The actions are registered when the integration is set up, not per entry."""
    set_sources(hass)
    await setup_entry(hass)
    assert hass.services.has_service(DOMAIN, "set_tank_state")
    assert hass.services.has_service(DOMAIN, "recalibrate")
