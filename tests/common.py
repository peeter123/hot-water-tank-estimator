"""Helpers for the Home Assistant tests: made-up sources, entries and a reference model."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hot_water_tank_estimator.const import (
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_HUMIDITY_SENSORS,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_VOLUME,
    CONF_WATER_METER,
    DOMAIN,
    STORAGE_VERSION,
)
from custom_components.hot_water_tank_estimator.estimator import TankConfig
from custom_components.hot_water_tank_estimator.model import (
    ModelOptions,
    Sources,
    TankModel,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

TANK = "sensor.tank_temperature"
METER = "sensor.water_meter"
ENERGY = "sensor.heat_energy"
POWER = "sensor.heat_power"
HEATING = "binary_sensor.heating_active"
FLOW = "sensor.flow_temperature"
RETURN = "sensor.return_temperature"
HUMIDITY = "sensor.bathroom_humidity"
COLD = "sensor.cold_water_temperature"
AMBIENT = "sensor.tank_ambient"

TITLE = "Hot water"
CELSIUS = {"unit_of_measurement": "°C", "device_class": "temperature"}

ATTRIBUTES: dict[str, dict[str, Any]] = {
    TANK: CELSIUS,
    METER: {"unit_of_measurement": "m³", "device_class": "water"},
    ENERGY: {"unit_of_measurement": "kWh", "device_class": "energy"},
    POWER: {"unit_of_measurement": "W", "device_class": "power"},
    HEATING: {},
    FLOW: CELSIUS,
    RETURN: CELSIUS,
    HUMIDITY: {"unit_of_measurement": "%", "device_class": "humidity"},
    COLD: CELSIUS,
    AMBIENT: CELSIUS,
}

FULL_OPTIONS: dict[str, Any] = {
    CONF_VOLUME: 281.0,
    CONF_TANK_SENSOR: TANK,
    CONF_SENSOR_HEIGHT: 50.0,
    CONF_WATER_METER: METER,
    CONF_ENERGY_COUNTER: ENERGY,
    CONF_HEATING_ACTIVE: HEATING,
    CONF_FLOW_SENSOR: FLOW,
    CONF_RETURN_SENSOR: RETURN,
    CONF_HUMIDITY_SENSORS: [HUMIDITY],
}
MINIMAL_OPTIONS: dict[str, Any] = {
    CONF_VOLUME: 281.0,
    CONF_TANK_SENSOR: TANK,
    CONF_SENSOR_HEIGHT: 50.0,
    CONF_WATER_METER: METER,
    CONF_ENERGY_COUNTER: ENERGY,
}
FULL_SOURCES = Sources(
    energy_counter=True,
    heating_binary=True,
    flow_return=True,
    humidity_sensors=(HUMIDITY,),
)


def set_sources(hass: HomeAssistant, **overrides: str) -> None:
    """Give every made-up source of the full setup a state (a few can be overridden by name)."""
    values = {
        TANK: "55.0",
        METER: "100.000",
        ENERGY: "10.0",
        HEATING: "off",
        FLOW: "20.0",
        RETURN: "20.0",
        HUMIDITY: "55.0",
    }
    values.update(overrides)
    for entity_id, state in values.items():
        hass.states.async_set(entity_id, state, ATTRIBUTES.get(entity_id, {}))


async def setup_fitted_entry(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    options: dict[str, Any] | None = None,
    ambient_fitted: str | None = None,
) -> MockConfigEntry:
    """Set up an entry whose store says that the setup fit is done with `ambient_fitted`.

    A reload then starts a fit only when the ambient sensor of the options is another one.
    """
    entry_id = "fitted-entry-id"
    hass_storage[f"{DOMAIN}.{entry_id}"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry_id}",
        "data": {"fit_done": True, "ambient_fit": ambient_fitted},
    }
    return await setup_entry(hass, options, entry_id=entry_id)


async def setup_entry(
    hass: HomeAssistant,
    options: dict[str, Any] | None = None,
    title: str = TITLE,
    entry_id: str | None = None,
) -> MockConfigEntry:
    """Add and set up an entry (the full setup unless options are given)."""
    extra = {} if entry_id is None else {"entry_id": entry_id}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        options=FULL_OPTIONS if options is None else options,
        **extra,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str
) -> str:
    """Return the entity ID of an entry's entity by its key."""
    found = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found is not None, f"no {domain} entity {key}"
    return found


def value(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    """Return the state of an entry's entity by its key."""
    state = hass.states.get(entity_id(hass, entry, domain, key))
    assert state is not None
    return state.state


class Oracle:
    """A model driven by the same inputs as the integration, to compare the entities with.

    It also mirrors the end-of-shower timer that the runtime gets in the options and timer
    group: the model is ticked at its next shower end before a later input.
    """

    def __init__(
        self,
        options: ModelOptions,
        sources: Sources,
        now: datetime,
        t_avg: float,
    ) -> None:
        """Create the reference model."""
        self.model = TankModel(options, sources, now, t_avg)
        self.flow: float | None = None
        self.ret: float | None = None

    def set(self, now: datetime, entity: str, state: str) -> None:
        """Apply a source state at a time, as the integration does."""
        model = self.model
        # The integration's end-of-shower timer fires at the deadline, between the inputs.
        deadline = model.next_shower_end
        if deadline is not None and deadline <= now:
            model.tick(deadline)
        number = None if state in ("unavailable", "unknown") else _float(state)
        match entity:
            case _ if entity == TANK:
                model.on_tank_sensor(now, number)
            case _ if entity == METER:
                model.on_water_meter(now, number, "m3")
            case _ if entity == ENERGY:
                model.on_energy(now, number)
            case _ if entity == POWER:
                model.on_power(now, number)
            case _ if entity == HEATING:
                model.on_heating(now, {"on": True, "off": False}.get(state))
            case _ if entity in (FLOW, RETURN):
                if entity == FLOW:
                    self.flow = number
                else:
                    self.ret = number
                model.on_flow_return(now, self.flow, self.ret)
            case _ if entity == HUMIDITY:
                model.on_humidity(now, HUMIDITY, number)
            case _ if entity == COLD:
                model.on_cold_water_sensor(now, number)
            case _ if entity == AMBIENT:
                model.on_ambient_sensor(now, number)


def _float(text: str) -> float | None:
    """Return a state as a number, None when it is not one."""
    try:
        return float(text)
    except ValueError:
        return None


class Rig:
    """Drives the made-up sources of an entry and a reference model with the same inputs."""

    def __init__(
        self,
        hass: HomeAssistant,
        freezer: Any,
        entry: MockConfigEntry,
        oracle: Oracle,
    ) -> None:
        """Create the rig."""
        self.hass = hass
        self.freezer = freezer
        self.entry = entry
        self.oracle = oracle

    @classmethod
    async def start(
        cls,
        hass: HomeAssistant,
        freezer: Any,
        *,
        options: dict[str, Any] | None = None,
        sources: Sources = FULL_SOURCES,
        states: dict[str, str] | None = None,
    ) -> Rig:
        """Freeze time, give the sources states, set up an entry and start a reference model."""
        freezer.move_to("2026-10-15T10:00:00+00:00")
        set_sources(hass, **(states or {}))
        entry = await setup_entry(hass, options)
        config = TankConfig.from_options(entry.options)
        now = dt_util.utcnow()
        tank = hass.states.get(TANK)
        reading = _float(tank.state) if tank else None
        oracle = Oracle(
            config.options, sources, now, 50.0 if reading is None else reading
        )
        for entity in config.routes:
            current = hass.states.get(entity)
            assert current is not None
            oracle.set(now, entity, current.state)
        return cls(hass, freezer, entry, oracle)

    async def set(
        self,
        entity: str,
        state: str,
        *,
        after: float = 0.0,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Advance time, change a source and give the reference model the same input."""
        self.freezer.tick(timedelta(seconds=after))
        self.hass.states.async_set(
            entity,
            state,
            ATTRIBUTES.get(entity, {}) if attributes is None else attributes,
        )
        await self.hass.async_block_till_done()
        self.oracle.set(dt_util.utcnow(), entity, state)

    async def tick(self, minutes: float = 5.0) -> None:
        """Advance time and fire the interval of the estimator and of the reference model."""
        self.freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(self.hass)
        await self.hass.async_block_till_done()
        self.oracle.model.tick(dt_util.utcnow())

    def read(self, domain: str, key: str) -> str:
        """Return the state of an entity of the entry."""
        return value(self.hass, self.entry, domain, key)

    def check(self) -> None:
        """Assert that the entities show what the reference model gives."""
        model = self.oracle.model
        outputs = model.outputs
        assert self.read("sensor", "tank_litres") == str(outputs.tank_litres)
        assert self.read("sensor", "shower_litres") == str(outputs.shower_litres)
        assert self.read("sensor", "percent_charged") == str(outputs.percent_charged)
        assert self.read("sensor", "shower_minutes") == str(outputs.shower_minutes)
        assert float(self.read("sensor", "tank_average")) == pytest.approx(
            model.t_avg, abs=0.006
        )
        assert float(self.read("sensor", "charged_temperature")) == pytest.approx(
            model.t_ch, abs=0.006
        )
        assert float(self.read("sensor", "cold_water_temperature")) == pytest.approx(
            model.t_cold, abs=0.006
        )
