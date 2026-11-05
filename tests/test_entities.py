"""Tests for the entities: units, classes, the device, the model store and the detection sensor (task 5.5)."""

from datetime import datetime, timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hot_water_tank_estimator.const import (
    CONF_AMBIENT_SENSOR,
    CONF_HUMIDITY_SENSORS,
    CONF_SENSOR_HEIGHT,
    DOMAIN,
    STORAGE_VERSION,
)
from custom_components.hot_water_tank_estimator.model import ModelOptions, TankModel
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .common import (
    AMBIENT,
    ATTRIBUTES,
    FULL_OPTIONS,
    FULL_SOURCES,
    METER,
    MINIMAL_OPTIONS,
    TANK,
    TITLE,
    Rig,
    entity_id,
    set_sources,
    setup_entry,
    value,
)

SENSORS = {
    "tank_litres": ("L", "volume_storage", "measurement"),
    "shower_litres": ("L", "volume_storage", "measurement"),
    "percent_charged": ("%", None, "measurement"),
    "shower_minutes": ("min", "duration", "measurement"),
    "charged_temperature": ("°C", "temperature", "measurement"),
    "tank_average": ("°C", "temperature", "measurement"),
    "cold_water_temperature": ("°C", "temperature", "measurement"),
    "heat_loss": ("W", "power", "measurement"),
    "tank_sensor_temperature": ("°C", "temperature", "measurement"),
}
SETTING_SENSORS = ("shower_end_time", "next_shower_time")
PARAMETER_SENSORS = {
    "other_hot_share": None,
    "startup_energy": "kWh",
    "loss_coefficient": "1/h",
    "thermocline_width": "%",
    "usable_fraction": "%",
}
ENTRY_ID = "tank-entry-id"
ERROR_SENSORS = ("calibration_samples", "last_charge_error", "mean_charge_error")


async def test_units_and_classes(hass: HomeAssistant) -> None:
    """Both remaining sensors are in litres, percent in %, minutes in min, temperatures in C."""
    set_sources(hass)
    entry = await setup_entry(hass)
    for key, (unit, device_class, state_class) in SENSORS.items():
        state = hass.states.get(entity_id(hass, entry, "sensor", key))
        assert state is not None, key
        assert state.attributes.get("unit_of_measurement") == unit, key
        assert state.attributes.get("device_class") == device_class, key
        assert state.attributes.get("state_class") == state_class, key
    for key in SETTING_SENSORS:
        state = hass.states.get(entity_id(hass, entry, "sensor", key))
        assert state is not None, key
        assert state.attributes.get("unit_of_measurement") == "min", key
        assert state.attributes.get("device_class") == "duration", key
        assert state.attributes.get("state_class") is None, key
    flow = hass.states.get(entity_id(hass, entry, "number", "shower_flow"))
    assert flow is not None
    assert flow.attributes.get("unit_of_measurement") == "L/min"
    assert flow.attributes.get("device_class") == "volume_flow_rate"
    assert flow.attributes.get("min") == 3.0
    assert flow.attributes.get("max") == 20.0
    assert flow.attributes.get("step") == 0.1


async def test_standing_loss_of_a_charged_tank(hass: HomeAssistant) -> None:
    """V 285 L, k 0.0039, T_avg 58 C and T_ambient 19.5 C: 0.0039 * 0.331 * 38.5 * 1000 = 50 W."""
    set_sources(hass)
    hass.states.async_set(AMBIENT, "19.5", ATTRIBUTES[AMBIENT])
    entry = await setup_entry(
        hass,
        {
            **FULL_OPTIONS,
            "volume": 285.0,
            "loss_coefficient": 0.0039,
            CONF_AMBIENT_SENSOR: AMBIENT,
        },
    )
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, entry, "sensor", "tank_litres"),
            "tank_average": 58,
            "charged_temperature": 58,
        },
        blocking=True,
    )
    assert value(hass, entry, "sensor", "heat_loss") == "50"
    # At or below the ambient temperature there is no loss.
    hass.states.async_set(AMBIENT, "60", ATTRIBUTES[AMBIENT])
    await hass.async_block_till_done()
    assert value(hass, entry, "sensor", "heat_loss") == "0"


async def test_the_tank_sensor_temperature_shows_the_reading(
    hass: HomeAssistant,
) -> None:
    """A tank sensor at 55.8 C and height 58 %: the sensor shows 55.8 with its source and height."""
    set_sources(hass, **{TANK: "55.8"})
    entry = await setup_entry(hass, {**FULL_OPTIONS, CONF_SENSOR_HEIGHT: 58.0})
    eid = entity_id(hass, entry, "sensor", "tank_sensor_temperature")
    assert er.async_get(hass).async_get(eid).entity_category is (
        er.EntityCategory.DIAGNOSTIC
    )
    assert er.async_get(hass).async_get(eid).disabled_by is None
    state = hass.states.get(eid)
    assert state is not None
    assert state.state == "55.8"
    assert state.attributes["source_entity"] == TANK
    assert state.attributes["sensor_height"] == 58
    assert state.attributes["friendly_name"] == "Hot water Tank sensor temperature"
    # It follows the source at once.
    hass.states.async_set(TANK, "54.2", ATTRIBUTES[TANK])
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "54.2"


async def test_the_tank_sensor_temperature_is_in_celsius(
    hass: HomeAssistant,
) -> None:
    """A tank sensor reading 132.8 F shows as 56.0 C."""
    set_sources(hass)
    hass.states.async_set(
        TANK, "132.8", {"unit_of_measurement": "°F", "device_class": "temperature"}
    )
    entry = await setup_entry(hass)
    assert value(hass, entry, "sensor", "tank_sensor_temperature") == "56.0"


@pytest.mark.parametrize("text", ["unavailable", "unknown", "warm"])
async def test_the_tank_sensor_temperature_is_unavailable_with_the_source(
    hass: HomeAssistant, text: str
) -> None:
    """The tank sensor becoming unavailable (unknown, not numeric) leaves the tank average as it is."""
    set_sources(hass)
    entry = await setup_entry(hass)
    average = value(hass, entry, "sensor", "tank_average")
    assert value(hass, entry, "sensor", "tank_sensor_temperature") == "55.0"
    hass.states.async_set(TANK, text, ATTRIBUTES[TANK])
    await hass.async_block_till_done()
    assert value(hass, entry, "sensor", "tank_sensor_temperature") == "unavailable"
    assert value(hass, entry, "sensor", "tank_average") == average
    hass.states.async_set(TANK, "53.0", ATTRIBUTES[TANK])
    await hass.async_block_till_done()
    assert value(hass, entry, "sensor", "tank_sensor_temperature") == "53.0"


async def test_the_tank_sensor_temperature_is_unavailable_without_a_source_state(
    hass: HomeAssistant,
) -> None:
    """A tank sensor with no state (removed, or not there yet) leaves the sensor unavailable."""
    set_sources(hass)
    entry = await setup_entry(hass)
    assert value(hass, entry, "sensor", "tank_sensor_temperature") == "55.0"
    hass.states.async_remove(TANK)
    await hass.async_block_till_done()
    assert value(hass, entry, "sensor", "tank_sensor_temperature") == "unavailable"


async def test_defaults_shown(hass: HomeAssistant) -> None:
    """Integration-setup scenario "Defaults shown": with a humidity sensor both shower times show 5 min."""
    set_sources(hass)
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    for key in SETTING_SENSORS:
        eid = entity_id(hass, entry, "sensor", key)
        assert registry.async_get(eid).entity_category is er.EntityCategory.DIAGNOSTIC
        assert registry.async_get(eid).disabled_by is None
        assert float(value(hass, entry, "sensor", key)) == 5.0
    shower_end = hass.states.get(entity_id(hass, entry, "sensor", "shower_end_time"))
    assert (
        shower_end.attributes["friendly_name"] == "Hot water Shower end after no water"
    )
    next_shower = hass.states.get(entity_id(hass, entry, "sensor", "next_shower_time"))
    assert next_shower.attributes["friendly_name"] == (
        "Hot water New shower draw while humid"
    )


async def test_no_humidity_sensor(hass: HomeAssistant) -> None:
    """Integration-setup scenario "No humidity sensor": the shower end shows 5 min, the other is unavailable."""
    set_sources(hass)
    entry = await setup_entry(hass, {**MINIMAL_OPTIONS, "long_draw_minutes": 8.0})
    assert float(value(hass, entry, "sensor", "shower_end_time")) == 5.0
    assert value(hass, entry, "sensor", "next_shower_time") == "unavailable"


async def test_diagnostic_sensors_and_their_source(hass: HomeAssistant) -> None:
    """The calibration sensors are diagnostic, and each parameter shows its source."""
    set_sources(hass)
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    for key, unit in PARAMETER_SENSORS.items():
        eid = entity_id(hass, entry, "sensor", key)
        assert registry.async_get(eid).entity_category is er.EntityCategory.DIAGNOSTIC
        state = hass.states.get(eid)
        assert state is not None
        assert state.attributes.get("unit_of_measurement") == unit
        assert state.attributes["source"] == "option"
    for key in ERROR_SENSORS:
        eid = entity_id(hass, entry, "sensor", key)
        assert registry.async_get(eid).entity_category is er.EntityCategory.DIAGNOSTIC
    assert value(hass, entry, "sensor", "calibration_samples") == "0"
    assert value(hass, entry, "sensor", "last_charge_error") == "unknown"
    assert value(hass, entry, "sensor", "mean_charge_error") == "unknown"
    assert value(hass, entry, "sensor", "thermocline_width") == "35.0"
    assert value(hass, entry, "sensor", "usable_fraction") == "85.0"
    assert value(hass, entry, "sensor", "other_hot_share") == "0.2"
    assert value(hass, entry, "sensor", "startup_energy") == "0.0"
    assert value(hass, entry, "sensor", "loss_coefficient") == "0.004"
    # The estimate sensors are not diagnostic.
    eid = entity_id(hass, entry, "sensor", "tank_litres")
    assert registry.async_get(eid).entity_category is None


async def test_every_entity_is_on_one_device_with_a_translated_name(
    hass: HomeAssistant,
) -> None:
    """One device per entry holds all the entities; the names come from the translations."""
    set_sources(hass)
    entry = await setup_entry(hass)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == TITLE
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 8 + 13 + 1 + 1 + 1 + 1 + 1
    assert {e.device_id for e in entities} == {devices[0].id}
    state = hass.states.get(entity_id(hass, entry, "sensor", "tank_litres"))
    assert state is not None
    assert state.attributes["friendly_name"] == "Hot water Hot water remaining"
    button = hass.states.get(entity_id(hass, entry, "button", "hot_water_ran_out"))
    assert button is not None
    assert button.attributes["friendly_name"] == "Hot water Hot water ran out"
    undo = hass.states.get(entity_id(hass, entry, "button", "undo_hot_water_ran_out"))
    assert undo is not None
    assert undo.state == "unavailable"
    assert undo.attributes["friendly_name"] == "Hot water Undo hot water ran out"
    lock = hass.states.get(entity_id(hass, entry, "switch", "shower_flow_locked"))
    assert lock is not None
    assert lock.state == "off"
    assert lock.attributes["friendly_name"] == "Hot water Shower flow locked"


async def test_two_tanks_have_two_devices(hass: HomeAssistant) -> None:
    """Each tank has its own device and its own entities."""
    set_sources(hass)
    hass.states.async_set("sensor.cellar_tank", "48.0", {"unit_of_measurement": "°C"})
    first = await setup_entry(hass)
    second = await setup_entry(
        hass, {**MINIMAL_OPTIONS, "tank_sensor": "sensor.cellar_tank"}, "Cellar"
    )
    devices = list(dr.async_get(hass).devices)
    assert {d.name for d in devices} == {TITLE, "Cellar"}
    assert value(hass, first, "sensor", "tank_average") == "55.0"
    assert value(hass, second, "sensor", "tank_average") == "48.0"


async def test_shower_detected_is_unavailable_without_detection(
    hass: HomeAssistant,
) -> None:
    """With no humidity sensor and the long-draw rule off, the binary sensor is unavailable."""
    set_sources(hass)
    entry = await setup_entry(hass, MINIMAL_OPTIONS)
    assert value(hass, entry, "binary_sensor", "shower_detected") == "unavailable"


async def test_shower_detected_with_the_long_draw_rule(hass: HomeAssistant) -> None:
    """The long-draw rule alone makes detection available."""
    set_sources(hass)
    entry = await setup_entry(hass, {**MINIMAL_OPTIONS, "long_draw_minutes": 3.0})
    assert value(hass, entry, "binary_sensor", "shower_detected") == "off"


async def test_shower_detected_follows_humidity(hass: HomeAssistant, freezer) -> None:
    """A humidity rise turns the binary sensor on; the room drying turns it off."""
    rig = await Rig.start(hass, freezer)
    assert rig.read("binary_sensor", "shower_detected") == "off"
    await rig.set("sensor.bathroom_humidity", "72.0", after=60)
    assert rig.read("binary_sensor", "shower_detected") == "on"
    await rig.set("sensor.bathroom_humidity", "56.0", after=1800)
    assert rig.read("binary_sensor", "shower_detected") == "off"


def stored_data(model: TankModel) -> dict:
    """Return the content of an entry's store holding a model."""
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY_ID}",
        "data": {"model": model.to_dict()},
    }


async def test_restart_restores_the_model_from_the_store(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """After a restart T_avg is 41.2 C and T_ch 56.0 C, as stored."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    model = TankModel(
        ModelOptions(volume=281.0), FULL_SOURCES, dt_util.utcnow(), 41.2, 56.0
    )
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = stored_data(model)
    # A sensor reading between the hot and the cold layer: no bound moves the model.
    set_sources(hass, **{TANK: "50.0"})
    entry = await setup_entry(hass, entry_id=ENTRY_ID)
    assert value(hass, entry, "sensor", "tank_average") == "41.2"
    assert value(hass, entry, "sensor", "charged_temperature") == "56.0"
    assert entry.runtime_data.model_restored


async def test_the_model_is_restored_with_the_tank_average_sensor_disabled(
    hass: HomeAssistant, freezer
) -> None:
    """A reload keeps T_avg when the user disabled the sensor that shows it."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=FULL_OPTIONS)
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_tank_average",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    hass.states.async_set(METER, "100.030", ATTRIBUTES[METER])
    await hass.async_block_till_done()
    average = entry.runtime_data.model.t_avg
    assert average < 55.0
    assert hass.states.get("sensor.hot_water_tank_average_temperature") is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.model_restored
    assert entry.runtime_data.model.t_avg == pytest.approx(average)
    assert entry.runtime_data.model.t_ch == pytest.approx(55.0, abs=0.01)


async def test_a_malformed_stored_model_is_ignored(
    hass: HomeAssistant, freezer, hass_storage, caplog: pytest.LogCaptureFixture
) -> None:
    """A stored model that cannot be read is ignored with a warning; the tank starts at the sensor."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY_ID}",
        "data": {"model": {"version": 99}},
    }
    set_sources(hass)
    entry = await setup_entry(hass, entry_id=ENTRY_ID)
    assert "Ignoring the stored model" in caplog.text
    assert not entry.runtime_data.model_restored
    assert value(hass, entry, "sensor", "tank_average") == "55.0"


async def test_a_reload_keeps_the_model(hass: HomeAssistant, freezer) -> None:
    """The state a reload restores is the state before it, including a draw."""
    rig = await Rig.start(hass, freezer)
    await rig.set("sensor.water_meter", "100.020", after=30)
    average = rig.read("sensor", "tank_average")
    charged = rig.read("sensor", "charged_temperature")
    assert average != charged
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert rig.read("sensor", "tank_average") == average
    assert rig.read("sensor", "charged_temperature") == charged
    assert rig.entry.runtime_data.model_restored


async def test_the_humidity_option_is_optional(hass: HomeAssistant) -> None:
    """An entry without humidity sensors sets up with the minimal sources."""
    set_sources(hass)
    entry = await setup_entry(hass, {**FULL_OPTIONS, CONF_HUMIDITY_SENSORS: []})
    assert entry.runtime_data.config.sources.humidity_sensors == ()
    assert entry.domain == DOMAIN


async def test_names_shown(hass: HomeAssistant) -> None:
    """A new entry titled "Hot Water Tank" gets the new names and entity IDs."""
    set_sources(hass)
    entry = await setup_entry(hass, title="Hot Water Tank")
    remaining = hass.states.get("sensor.hot_water_tank_hot_water_remaining")
    assert remaining is not None
    assert remaining.attributes["friendly_name"] == "Hot Water Tank Hot water remaining"
    level = hass.states.get("sensor.hot_water_tank_charge_level")
    assert level is not None
    assert level.attributes["friendly_name"] == "Hot Water Tank Charge level"
    loss = hass.states.get("sensor.hot_water_tank_heat_loss")
    assert loss is not None
    assert loss.attributes["friendly_name"] == "Hot Water Tank Heat loss"
    ran_out = hass.states.get("button.hot_water_tank_hot_water_ran_out")
    assert ran_out is not None
    assert ran_out.attributes["friendly_name"] == "Hot Water Tank Hot water ran out"
    flow = hass.states.get("number.hot_water_tank_shower_flow")
    assert flow is not None
    assert flow.attributes["friendly_name"] == "Hot Water Tank Shower flow"
    assert entry.title == "Hot Water Tank"


async def test_unique_ids_unchanged(hass: HomeAssistant) -> None:
    """Entities registered under the old entity IDs keep them, and show the new names."""
    set_sources(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Hot Water Tank", options=FULL_OPTIONS)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, old_id in (
        ("tank_litres", "hot_water_tank_tank_water_remaining"),
        ("percent_charged", "hot_water_tank_percent_charged"),
    ):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            suggested_object_id=old_id,
        )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    remaining = hass.states.get("sensor.hot_water_tank_tank_water_remaining")
    assert remaining is not None
    assert remaining.attributes["friendly_name"] == "Hot Water Tank Hot water remaining"
    level = hass.states.get("sensor.hot_water_tank_percent_charged")
    assert level is not None
    assert level.attributes["friendly_name"] == "Hot Water Tank Charge level"
    assert hass.states.get("sensor.hot_water_tank_hot_water_remaining") is None


def _time(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> datetime | None:
    """Return the timestamp a sensor shows, None while it is unknown."""
    text = value(hass, entry, "sensor", key)
    assert text != "unavailable"
    return None if text == "unknown" else dt_util.parse_datetime(text)


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    """Return the wall-clock time on the rig's day in UTC, the zone the sensors report."""
    return datetime(2026, 10, 15, hour, minute, second, tzinfo=dt_util.UTC)


async def _fire(hass: HomeAssistant) -> None:
    """Fire the timers that are due at the frozen time."""
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_shower_ends_counts_down(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Shower ends counts down": last increase 20:25:21, ends 20:30:21, then unknown."""
    rig = await Rig.start(hass, freezer)
    assert _time(hass, rig.entry, "shower_ends") is None
    freezer.move_to(_at(20, 20))
    await rig.set("sensor.bathroom_humidity", "55.0")
    await rig.set("sensor.bathroom_humidity", "72.0", after=4 * 60 + 51)
    await rig.set("sensor.water_meter", "100.020", after=30)
    assert dt_util.utcnow() == _at(20, 25, 21)
    assert rig.read("binary_sensor", "shower_detected") == "on"
    assert _time(hass, rig.entry, "shower_ends") == _at(20, 30, 21)
    freezer.move_to(_at(20, 30, 21))
    await _fire(hass)
    assert rig.read("binary_sensor", "shower_detected") == "off"
    assert _time(hass, rig.entry, "shower_ends") is None


async def test_draw_in_the_humid_bathroom(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Draw in the humid bathroom": 20:45:00, unknown at 20:42:00 by the timer alone."""
    rig = await Rig.start(hass, freezer)
    freezer.move_to(_at(20, 20))
    await rig.set("sensor.bathroom_humidity", "55.0")
    await rig.set("sensor.bathroom_humidity", "72.0", after=8 * 60 + 40)
    await rig.set("sensor.water_meter", "100.020", after=30)
    assert rig.read("binary_sensor", "shower_detected") == "on"
    freezer.move_to(_at(20, 34, 10))
    await _fire(hass)
    assert rig.read("binary_sensor", "shower_detected") == "off"
    assert _time(hass, rig.entry, "draw_counts_as_shower") is None
    # The interval tick has fired and is set again for 20:45:00, so none falls before 20:42:02.
    freezer.move_to(_at(20, 40))
    await _fire(hass)
    await rig.set("sensor.water_meter", "100.040")
    assert _time(hass, rig.entry, "draw_counts_as_shower") == _at(20, 45)
    await rig.set("sensor.water_meter", "100.060", after=60)
    assert dt_util.utcnow() == _at(20, 41)
    assert _time(hass, rig.entry, "draw_counts_as_shower") == _at(20, 45)
    # No reading and no interval tick follow: the session expiry timer clears it.
    assert rig.entry.runtime_data.shower_timer_at == _at(20, 42, 1)
    freezer.move_to(_at(20, 42, 1))
    await _fire(hass)
    assert _time(hass, rig.entry, "draw_counts_as_shower") is None


async def test_long_draw_without_humidity_sensor(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Long draw without humidity sensor": first increase 07:00:00, 07:08:00."""
    freezer.move_to(_at(7, 0))
    set_sources(hass)
    entry = await setup_entry(hass, {**MINIMAL_OPTIONS, "long_draw_minutes": 8.0})
    assert _time(hass, entry, "draw_counts_as_shower") is None
    hass.states.async_set(METER, "100.010", ATTRIBUTES[METER])
    await hass.async_block_till_done()
    assert _time(hass, entry, "draw_counts_as_shower") == _at(7, 8)


async def test_the_countdown_sensors_are_unavailable_without_a_detection_method(
    hass: HomeAssistant,
) -> None:
    """No humidity sensor and no long draw duration: both countdown sensors are unavailable."""
    set_sources(hass)
    entry = await setup_entry(hass, MINIMAL_OPTIONS)
    assert not entry.runtime_data.model.detection_available
    for key in ("shower_ends", "draw_counts_as_shower"):
        assert value(hass, entry, "sensor", key) == "unavailable"
