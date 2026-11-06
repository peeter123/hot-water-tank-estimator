"""Tests for the runtime: the sources drive the model and the entities show it (tasks 5.3, 5.7)."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hot_water_tank_estimator.model import EventKind
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .common import (
    ATTRIBUTES,
    ENERGY,
    FLOW,
    HEATING,
    HUMIDITY,
    METER,
    MINIMAL_OPTIONS,
    POWER,
    RETURN,
    TANK,
    Rig,
    set_sources,
    setup_entry,
    value,
)


async def shower(rig: Rig) -> None:
    """A shower: 10 L, humidity up, 60 L more in steps of 10 L."""
    await rig.set(METER, "100.010", after=60)
    await rig.set(HUMIDITY, "70.0", after=30)
    for step in range(2, 8):
        await rig.set(METER, f"{100 + 0.01 * step:.3f}", after=10)


async def test_the_entities_follow_a_shower(hass: HomeAssistant, freezer) -> None:
    """A shower detected by humidity takes mix energy out, as the reference model says."""
    rig = await Rig.start(hass, freezer)
    rig.check()
    assert rig.read("sensor", "tank_litres") == "239"
    await shower(rig)
    rig.check()
    assert int(rig.read("sensor", "tank_litres")) < 200
    assert rig.read("binary_sensor", "shower_detected") == "on"
    drawn = [
        e
        for e in hass.config_entries.async_get_entry(
            rig.entry.entry_id
        ).runtime_data.model.events
        if e.kind == EventKind.DRAW and e.change.get("mixed")
    ]
    assert sum(e.change["litres"] for e in drawn) == pytest.approx(60.0)


async def test_the_entities_follow_a_heating_run(hass: HomeAssistant, freezer) -> None:
    """A run adds heat, and its end charges the tank at the flow and return mean."""
    rig = await Rig.start(hass, freezer)
    await shower(rig)
    low = float(rig.read("sensor", "tank_average"))
    await rig.set(HEATING, "on", after=600)
    await rig.set(FLOW, "58.0", after=1)
    await rig.set(RETURN, "40.0", after=1)
    for step in range(1, 17):
        await rig.set(ENERGY, f"{10 + 0.5 * step:.1f}", after=60)
        rig.check()
    assert float(rig.read("sensor", "tank_average")) > low
    await rig.set(FLOW, "57.0", after=60)
    await rig.set(RETURN, "55.0", after=1)
    await rig.set(HEATING, "off", after=30)
    rig.check()
    assert rig.read("sensor", "percent_charged") == "100"
    assert float(rig.read("sensor", "tank_average")) == pytest.approx(56.0)
    assert float(rig.read("sensor", "charged_temperature")) == pytest.approx(56.0)


async def test_the_interval_applies_standing_loss(hass: HomeAssistant, freezer) -> None:
    """Every 5 minutes the model loses heat, even without any source change."""
    rig = await Rig.start(hass, freezer)
    before = float(rig.read("sensor", "tank_average"))
    for _ in range(12):
        await rig.tick()
    rig.check()
    assert float(rig.read("sensor", "tank_average")) < before


async def test_first_start_charges_at_the_tank_sensor(
    hass: HomeAssistant, freezer
) -> None:
    """A new entry starts with the tank at the sensor's reading."""
    rig = await Rig.start(hass, freezer, states={TANK: "56.0"})
    assert rig.read("sensor", "tank_average") == "56.0"
    assert rig.read("sensor", "charged_temperature") == "56.0"


async def test_first_start_without_a_tank_reading(hass: HomeAssistant, freezer) -> None:
    """With the tank sensor unavailable the tank starts at 50 C."""
    rig = await Rig.start(hass, freezer, states={TANK: "unavailable"})
    assert rig.read("sensor", "tank_average") == "50.0"
    assert rig.read("sensor", "charged_temperature") == "50.0"


async def test_the_meter_unit_is_read_from_the_state(
    hass: HomeAssistant, freezer
) -> None:
    """A water meter in gallons draws 3.785 litres per gallon."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    hass.states.async_set(METER, "50.0", {"unit_of_measurement": "gal"})
    entry = await setup_entry(hass, {**MINIMAL_OPTIONS})
    model = entry.runtime_data.model
    freezer.tick(timedelta(seconds=30))
    hass.states.async_set(METER, "52.0", {"unit_of_measurement": "gal"})
    await hass.async_block_till_done()
    draws = [e for e in model.events if e.kind == EventKind.DRAW]
    assert draws[-1].change["litres"] == pytest.approx(2 * 3.785411784)


async def test_water_meter_offline_briefly(hass: HomeAssistant, freezer) -> None:
    """A meter that is unavailable for 2 minutes and returns 3 L higher draws 3 L."""
    rig = await Rig.start(hass, freezer)
    before = float(rig.read("sensor", "tank_average"))
    await rig.set(METER, "unavailable", after=10)
    rig.check()
    assert float(rig.read("sensor", "tank_average")) == pytest.approx(before, abs=0.01)
    await rig.set(METER, "100.003", after=110)
    rig.check()
    model = rig.entry.runtime_data.model
    draws = [e for e in model.events if e.kind == EventKind.DRAW]
    assert draws[-1].change == {"litres": pytest.approx(3.0), "mixed": False}
    assert float(rig.read("sensor", "tank_average")) < before


async def test_energy_counter_reset(hass: HomeAssistant, freezer) -> None:
    """A counter that drops from 151.5 to 0.2 kWh applies no heat and restarts at 0.2."""
    rig = await Rig.start(hass, freezer, states={ENERGY: "151.5"})
    await rig.set(HEATING, "on", after=60)
    await rig.set(ENERGY, "151.7", after=60)
    before = float(rig.read("sensor", "tank_average"))
    await rig.set(ENERGY, "0.2", after=60)
    rig.check()
    assert float(rig.read("sensor", "tank_average")) == pytest.approx(before, abs=0.01)
    await rig.set(ENERGY, "0.7", after=60)
    rig.check()
    heats = [
        e.change["energy_kwh"]
        for e in rig.entry.runtime_data.model.events
        if e.kind == EventKind.HEAT and "energy_kwh" in e.change
    ]
    assert heats == [pytest.approx(0.2), pytest.approx(0.5)]


async def test_tank_sensor_flickers(hass: HomeAssistant, freezer) -> None:
    """A tank sensor that is unavailable for 2 s gets no bound, and the outputs keep updating."""
    rig = await Rig.start(hass, freezer)
    await rig.set(TANK, "unavailable", after=60)
    marker = len(rig.entry.runtime_data.model.events)
    await rig.set(METER, "100.020", after=1)
    rig.check()
    kinds = {e.kind for e in rig.entry.runtime_data.model.events[marker:]}
    assert EventKind.SENSOR_BOUND not in kinds
    assert EventKind.DRAW in kinds
    assert rig.entry.runtime_data.model.tank_sensor is None
    await rig.set(TANK, "55.0", after=1)
    rig.check()
    assert rig.entry.runtime_data.model.tank_sensor == 55.0


async def test_a_removed_source_counts_as_unavailable(
    hass: HomeAssistant, freezer
) -> None:
    """A source whose entity disappears pauses its part of the model."""
    rig = await Rig.start(hass, freezer)
    hass.states.async_remove(METER)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    await rig.set(METER, "100.004", after=30)
    rig.check()


async def test_power_in_kilowatts_is_converted(hass: HomeAssistant, freezer) -> None:
    """A heat power sensor in kW is read in W: 2 kW for an hour is 2 kWh."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    options = {k: v for k, v in MINIMAL_OPTIONS.items() if k != "energy_counter"} | {
        "power_sensor": POWER
    }
    hass.states.async_set(POWER, "0.0", {"unit_of_measurement": "kW"})
    entry = await setup_entry(hass, options)
    model = entry.runtime_data.model
    # No heating binary: the power threshold (100 W) decides.
    freezer.tick(timedelta(minutes=1))
    hass.states.async_set(POWER, "2.0", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    assert model.heating
    freezer.tick(timedelta(hours=1))
    hass.states.async_set(POWER, "0.0", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    heat = [
        e for e in model.events if e.kind == EventKind.HEAT and "energy_kwh" in e.change
    ]
    assert sum(e.change["energy_kwh"] for e in heat) == pytest.approx(2.0, rel=0.01)


async def test_temperatures_in_fahrenheit_are_converted(
    hass: HomeAssistant, freezer
) -> None:
    """A tank sensor in F is read in C."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    hass.states.async_set(TANK, "131.0", {"unit_of_measurement": "°F"})
    entry = await setup_entry(hass, {**MINIMAL_OPTIONS})
    assert value(hass, entry, "sensor", "tank_average") == "55.0"


async def test_options_use_the_sensor_height_as_a_fraction(
    hass: HomeAssistant, freezer
) -> None:
    """A sensor height of 65 % is 0.65 in the model."""
    set_sources(hass)
    entry = await setup_entry(hass, {**MINIMAL_OPTIONS, "sensor_height": 65.0})
    assert entry.runtime_data.model.options.sensor_height == pytest.approx(0.65)
    assert entry.runtime_data.config.options.volume == 281.0


async def test_a_replaced_energy_counter_starts_a_new_baseline(
    hass: HomeAssistant, freezer
) -> None:
    """A higher counter on a new entity is a new start, not heat since the old counter."""
    rig = await Rig.start(hass, freezer, states={ENERGY: "10.0", HEATING: "on"})
    assert rig.entry.runtime_data.model.heating
    hass.states.async_set(
        "sensor.other_energy", "500.0", {"unit_of_measurement": "kWh"}
    )
    hass.config_entries.async_update_entry(
        rig.entry,
        options={**rig.entry.options, "energy_counter": "sensor.other_energy"},
    )
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    model = rig.entry.runtime_data.model
    assert model.heating

    def heat() -> list[float]:
        return [
            e.change["energy_kwh"]
            for e in model.events
            if e.kind == EventKind.HEAT and "energy_kwh" in e.change
        ]

    assert heat() == []
    freezer.tick(timedelta(seconds=60))
    hass.states.async_set(
        "sensor.other_energy", "500.5", {"unit_of_measurement": "kWh"}
    )
    await hass.async_block_till_done()
    assert heat() == [pytest.approx(0.5)]


async def test_the_shower_ends_on_the_timer_at_its_deadline(
    hass: HomeAssistant, freezer
) -> None:
    """With no reading and no interval tick, the binary sensor turns off at the shower end time."""
    rig = await Rig.start(hass, freezer)
    start = dt_util.utcnow()
    runtime = rig.entry.runtime_data
    await shower(rig)
    assert rig.read("binary_sensor", "shower_detected") == "on"
    deadline = runtime.model.next_shower_end
    assert deadline is not None
    # The interval ticks fall every 5 minutes from the start: none is in (deadline - 1 s, deadline].
    assert (deadline - start).total_seconds() % 300 > 1
    freezer.move_to(deadline - timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert rig.read("binary_sensor", "shower_detected") == "on"
    freezer.move_to(deadline)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert rig.read("binary_sensor", "shower_detected") == "off"
    assert runtime.model.next_shower_end is None
    assert runtime.shower_timer_at is None


async def test_one_timer_follows_the_deadline_and_a_stop_leaves_none(
    hass: HomeAssistant, freezer
) -> None:
    """Each meter increase moves the one pending timer, and stopping the entry cancels it."""
    rig = await Rig.start(hass, freezer)
    runtime = rig.entry.runtime_data
    await shower(rig)
    first = runtime.shower_timer_at
    assert first is not None
    await rig.set(METER, "100.080", after=60)
    assert runtime.shower_timer_at == runtime.model.next_shower_end
    assert runtime.shower_timer_at > first
    pending = runtime.model.next_shower_end
    await hass.config_entries.async_unload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert runtime.shower_timer_at is None
    events = len(runtime.model.events)
    freezer.move_to(pending + timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert runtime.model.next_shower_end == pending
    assert len(runtime.model.events) == events


# ----- humidity silence (integration-setup: state survives a restart, shower countdown) -------


def _silent(rig: Rig, minutes_after_start: float) -> bool:
    """Whether the rig's humidity sensor counts as silent at a time after the rig's start (10:00)."""
    start = dt_util.parse_datetime("2026-10-15T10:00:00+00:00")
    assert start is not None
    model = rig.entry.runtime_data.model
    return model.humidity_silent(
        HUMIDITY, start + timedelta(minutes=minutes_after_start)
    )


async def test_reload_during_a_humidity_silence(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Reload during a humidity silence": silent 30 minutes after the reload."""
    rig = await Rig.start(hass, freezer)  # the sensor reported at 10:00
    await rig.tick(minutes=90)  # 11:30
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert dt_util.utcnow() == dt_util.parse_datetime("2026-10-15T11:30:00+00:00")
    assert not _silent(rig, 119)
    assert _silent(rig, 120)  # 12:00, 30 minutes after the reload, not 13:30


async def test_a_new_entry_reads_the_last_report_of_a_humidity_state(
    hass: HomeAssistant, freezer
) -> None:
    """A state older than the start counts from its `last_reported`: the first feed does not restart a silence."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)  # the humidity state is reported at 10:00
    freezer.move_to("2026-10-15T11:30:00+00:00")
    entry = await setup_entry(hass)
    model = entry.runtime_data.model
    start = dt_util.utcnow()
    assert not model.humidity_silent(HUMIDITY, start + timedelta(minutes=29))
    assert model.humidity_silent(HUMIDITY, start + timedelta(minutes=30))


async def test_an_unchanged_report_keeps_the_sensor_from_going_silent(
    hass: HomeAssistant, freezer
) -> None:
    """A report that repeats the value moves only `last_reported`: the tick passes it on."""
    rig = await Rig.start(hass, freezer)  # reported at 10:00
    await rig.tick(minutes=115)  # 11:55
    # Same state, same attributes: Home Assistant fires `state_reported` and moves last_reported.
    hass.states.async_set(HUMIDITY, "55.0", ATTRIBUTES[HUMIDITY])
    await hass.async_block_till_done()
    state = hass.states.get(HUMIDITY)
    assert state is not None
    assert state.last_reported > state.last_changed
    await rig.tick(minutes=65)  # 13:00, 3 hours after the last change
    model = rig.entry.runtime_data.model
    assert not model.humidity_silent(HUMIDITY, dt_util.utcnow())
    assert model.humidity_silent(HUMIDITY, dt_util.utcnow() + timedelta(minutes=56))


async def test_draw_while_the_humidity_sensor_is_silent(
    hass: HomeAssistant, freezer
) -> None:
    """Integration-setup scenario "Draw while the humidity sensor is silent": 17:54:32 gives 17:59:32."""
    rig = await Rig.start(hass, freezer)  # the sensor reported at 10:00
    freezer.move_to("2026-10-15T17:54:32+00:00")
    await rig.set(METER, "100.001")
    countdown = value(hass, rig.entry, "sensor", "draw_counts_as_shower")
    assert dt_util.parse_datetime(countdown) == dt_util.parse_datetime(
        "2026-10-15T17:59:32+00:00"
    )
    assert rig.read("binary_sensor", "shower_detected") == "off"
    for step in range(2, 12):  # a reading every 30 seconds keeps the session open
        await rig.set(METER, f"{100 + 0.001 * step:.3f}", after=30)
        expected = "on" if step == 11 else "off"
        assert rig.read("binary_sensor", "shower_detected") == expected
    assert dt_util.utcnow() == dt_util.parse_datetime("2026-10-15T17:59:32+00:00")
