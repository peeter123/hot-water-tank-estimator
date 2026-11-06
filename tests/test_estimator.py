"""Tests for the runtime: the sources drive the model and the entities show it (tasks 5.3, 5.7)."""

from datetime import timedelta
import json
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hot_water_tank_estimator.const import DOMAIN
from custom_components.hot_water_tank_estimator.estimator import TankEstimator
from custom_components.hot_water_tank_estimator.model import EventKind
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
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


# ----- repair issues (integration-setup: sources that stay unavailable) -----------------------


def _issue(hass: HomeAssistant, rig: Rig, entity: str) -> ir.IssueEntry | None:
    """Return the repair issue of an entity of the rig's entry, None when there is none."""
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{rig.entry.entry_id}_{entity}")


def _issue_text(key: str) -> str:
    """Return the description of a repair issue translation."""
    path = Path(__file__).parent.parent / "custom_components" / DOMAIN / "strings.json"
    return json.loads(path.read_text("utf-8"))["issues"][key]["description"]


async def test_water_meter_out_for_40_minutes(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Water meter out for 40 minutes": the issue names the tank and the meter."""
    rig = await Rig.start(hass, freezer)
    hass.config_entries.async_update_entry(rig.entry, title="Hot Water Tank")
    await rig.set(METER, "unavailable")
    for _ in range(5):  # 25 minutes
        await rig.tick()
    assert _issue(hass, rig, METER) is None
    await rig.tick(minutes=5)
    assert _issue(hass, rig, METER) is not None  # 30 minutes: the threshold is reached
    await rig.tick(minutes=10)  # 40 minutes
    issue = _issue(hass, rig, METER)
    assert issue is not None
    assert issue.translation_key == "source_unavailable_water_meter"
    assert issue.translation_placeholders == {
        "tank": "Hot Water Tank",
        "entity": METER,
        "threshold": "30 minutes",
    }
    text = _issue_text("source_unavailable_water_meter")
    assert "{tank}" in text
    assert "{entity}" in text
    assert "Draws are not counted" in text
    assert issue.is_fixable is False
    assert issue.is_persistent is False
    assert issue.severity == ir.IssueSeverity.WARNING
    assert rig.entry.runtime_data.open_issues == [f"{rig.entry.entry_id}_{METER}"]


async def test_short_dropout(
    hass: HomeAssistant, freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration-setup scenario "Short dropout": 2 seconds of the tank sensor, 19 minutes of the detector."""
    rig = await Rig.start(hass, freezer)
    checks: list[str] = []
    check = TankEstimator.__dict__["_check_sources"]

    def spy(self, now) -> None:
        checks.append(now.strftime("%H:%M"))
        check(self, now)

    monkeypatch.setattr(TankEstimator, "_check_sources", spy)
    await rig.set(TANK, "unavailable")
    await rig.set(TANK, "55.0", after=2)
    await rig.set(HEATING, "unavailable")
    await rig.tick(minutes=5)
    await rig.tick(minutes=5)
    await rig.tick(minutes=5)
    await rig.set(
        ENERGY, "10.1", after=4 * 60
    )  # 19 minutes: a changed state checks the sources
    assert checks[-1] == "10:19"
    assert _issue(hass, rig, TANK) is None
    assert _issue(hass, rig, HEATING) is None
    assert rig.entry.runtime_data.open_issues == []


async def test_source_back(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Source back": the issue is removed at once when the counter reports."""
    rig = await Rig.start(hass, freezer)
    await rig.set(ENERGY, "unavailable")
    await rig.tick(minutes=30)
    assert _issue(hass, rig, ENERGY) is not None
    await rig.set(ENERGY, "10.1")
    assert _issue(hass, rig, ENERGY) is None
    assert rig.entry.runtime_data.open_issues == []


async def test_silent_humidity_sensor(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Silent humidity sensor": last report 2 hours ago, silence time 2 hours."""
    rig = await Rig.start(hass, freezer)  # the sensor reported at 10:00
    await rig.tick(minutes=115)
    assert _issue(hass, rig, HUMIDITY) is None
    await rig.tick(minutes=5)  # 12:00
    issue = _issue(hass, rig, HUMIDITY)
    assert issue is not None
    assert issue.translation_key == "source_unavailable_bathroom_humidity"
    assert issue.translation_placeholders == {
        "tank": "Hot water",
        "entity": HUMIDITY,
        "threshold": "2 hours",
    }
    assert "draw length" in _issue_text("source_unavailable_bathroom_humidity")
    await rig.set(HUMIDITY, "56.0")  # a new report ends the silence at once
    assert _issue(hass, rig, HUMIDITY) is None


async def test_entry_removed(hass: HomeAssistant, freezer) -> None:
    """Integration-setup scenario "Entry removed": the repair issues go with the tank."""
    rig = await Rig.start(hass, freezer)
    await rig.set(METER, "unavailable")
    await rig.tick(minutes=30)
    assert _issue(hass, rig, METER) is not None
    entry_id = rig.entry.entry_id
    assert await hass.config_entries.async_remove(entry_id)
    await hass.async_block_till_done()
    assert not [
        key
        for key in ir.async_get(hass).issues
        if key[0] == DOMAIN and key[1].startswith(entry_id)
    ]


async def test_entry_removed_while_not_loaded(hass: HomeAssistant, freezer) -> None:
    """The removal hook deletes an issue that is left in the registry of an unloaded entry."""
    rig = await Rig.start(hass, freezer)
    entry_id = rig.entry.entry_id
    assert await hass.config_entries.async_unload(entry_id)
    await hass.async_block_till_done()
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{entry_id}_{METER}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="source_unavailable_water_meter",
    )
    assert _issue(hass, rig, METER) is not None
    assert await hass.config_entries.async_remove(entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, rig, METER) is None


async def test_unload_removes_the_issues_and_a_reload_raises_them_again(
    hass: HomeAssistant, freezer
) -> None:
    """A source still out since before the reload raises its issue again at once."""
    rig = await Rig.start(hass, freezer)
    await rig.set(METER, "unavailable")
    await rig.tick(minutes=30)
    assert _issue(hass, rig, METER) is not None
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, rig, METER) is None
    assert await hass.config_entries.async_setup(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, rig, METER) is not None


async def test_a_missing_source_counts_from_the_start(
    hass: HomeAssistant, freezer
) -> None:
    """A missing entity is out from the estimator start, a non-numeric state from its last change."""
    freezer.move_to("2026-10-15T09:40:00+00:00")
    set_sources(hass)
    hass.states.async_set(METER, "abc", ATTRIBUTES[METER])
    freezer.move_to("2026-10-15T10:00:00+00:00")
    hass.states.async_remove(ENERGY)
    entry = await setup_entry(hass)
    registry = ir.async_get(hass)

    async def fire(minutes: int) -> None:
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    def has(entity: str) -> bool:
        return (
            registry.async_get_issue(DOMAIN, f"{entry.entry_id}_{entity}") is not None
        )

    await fire(5)
    assert not has(METER)
    await fire(5)  # 10:10: the meter has been non-numeric since 09:40
    assert has(METER)
    assert not has(ENERGY)
    for _ in range(3):
        await fire(5)
    assert not has(ENERGY)  # 10:25
    await fire(5)  # 10:30 is 30 minutes after the start
    assert has(ENERGY)


async def test_a_source_that_disappears_counts_from_then(
    hass: HomeAssistant, freezer
) -> None:
    """A state removed at runtime counts from its removal, not from the start."""
    rig = await Rig.start(hass, freezer)
    await rig.tick(minutes=40)
    hass.states.async_remove(ENERGY)
    await hass.async_block_till_done()
    assert _issue(hass, rig, ENERGY) is None
    await rig.tick(minutes=25)
    assert _issue(hass, rig, ENERGY) is None
    await rig.tick(minutes=5)  # 30 minutes after it disappeared
    assert _issue(hass, rig, ENERGY) is not None
    await rig.set(ENERGY, "10.0")
    assert _issue(hass, rig, ENERGY) is None
