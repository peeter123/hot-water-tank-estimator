"""Tests for calibration in the runtime: the setup fit from the recorder, the store, the button (task 5.4)."""

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.hot_water_tank_estimator.calibration import CLOSURE, SENSOR_START
from custom_components.hot_water_tank_estimator.const import (
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_HUMIDITY_SENSORS,
    CONF_LOCKS,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_VOLUME,
    CONF_WATER_METER,
    DOMAIN,
)
from custom_components.hot_water_tank_estimator.estimator import TankConfig, _Tolerant
from custom_components.hot_water_tank_estimator.history import async_read_history
from custom_components.hot_water_tank_estimator.model import EventKind
from custom_components.hot_water_tank_estimator.setup_fit import (
    History,
    history_from_fixture,
    setup_fit,
)
from homeassistant.components import persistent_notification
from homeassistant.components.persistent_notification import UpdateType
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .common import (
    ENERGY,
    FULL_OPTIONS,
    HEATING,
    HUMIDITY,
    METER,
    TANK,
    Rig,
    entity_id,
    setup_entry,
    value,
)

FIXTURES = Path(__file__).parent / "fixtures"


def week_options() -> dict:
    """Return entry options for the entities of the week fixture."""
    return {
        CONF_VOLUME: 281.0,
        CONF_SENSOR_HEIGHT: 50.0,
        CONF_TANK_SENSOR: "sensor.tank_temperature",
        CONF_WATER_METER: "sensor.water_meter",
        CONF_ENERGY_COUNTER: "sensor.dhw_energy",
        CONF_HEATING_ACTIVE: "binary_sensor.dhw_heating",
        CONF_FLOW_SENSOR: "sensor.flow_temperature",
        CONF_RETURN_SENSOR: "sensor.return_temperature",
        CONF_HUMIDITY_SENSORS: ["sensor.bathroom_humidity"],
    }


async def record_fixture(hass: HomeAssistant, freezer, name: str) -> datetime:
    """Write a fixture's states to the recorder at their times. Returns the end of the window."""
    # Thousands of statements: logging each one at INFO more than doubles the time.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    data = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    rows = sorted(
        (datetime.fromisoformat(time), entity, state, entry.get("unit_of_measurement"))
        for entity, entry in data["entities"].items()
        for time, state in entry["states"]
    )
    for time, entity, state, unit in rows:
        freezer.move_to(time)
        hass.states.async_set(
            entity, state, {} if unit is None else {"unit_of_measurement": unit}
        )
    end = datetime.fromisoformat(data["window"]["end"])
    freezer.move_to(end)
    await async_wait_recording_done(hass)
    return end


async def test_setup_fit_from_the_recorder(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    enable_custom_integrations: None,
    freezer,
) -> None:
    """A new entry replays the week from the recorder: 7 samples and the parameters of the fit."""
    await record_fixture(hass, freezer, "week")
    entry = await setup_entry(hass, week_options())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, "sensor", "calibration_samples") == "7"
    share = float(value(hass, entry, "sensor", "other_hot_share"))
    startup = float(value(hass, entry, "sensor", "startup_energy"))
    loss = float(value(hass, entry, "sensor", "loss_coefficient"))
    assert share == pytest.approx(0.105, abs=0.01)
    assert startup == pytest.approx(2.19, abs=0.1)
    assert loss == pytest.approx(0.0040, abs=0.0005)
    for key in ("other_hot_share", "startup_energy"):
        state = hass.states.get(entity_id(hass, entry, "sensor", key))
        assert state is not None
        assert state.attributes["source"] == "setup_fit"
    # The same numbers as the pure setup fit on the fixture.
    data = json.loads((FIXTURES / "week.json").read_text("utf-8"))
    fit = setup_fit(
        history_from_fixture(data), TankConfig.from_options(week_options()).options
    )
    assert share == pytest.approx(fit.parameters["other_hot_share"][0], abs=0.002)
    assert startup == pytest.approx(fit.parameters["startup_energy"][0], abs=0.02)
    width = float(value(hass, entry, "sensor", "thermocline_width"))
    assert width == pytest.approx(fit.parameters["thermocline_width"][0] * 100, abs=0.5)
    state = hass.states.get(entity_id(hass, entry, "sensor", "thermocline_width"))
    assert state is not None
    assert state.attributes["source"] == fit.parameters["thermocline_width"][1]
    mean_error = fit.calibrator.mean_abs_error()
    assert mean_error is not None
    assert float(value(hass, entry, "sensor", "mean_charge_error")) == pytest.approx(
        mean_error, abs=0.05
    )
    # The fit ran in the background and saved the calibration. A reload restores it instead
    # of fitting again.
    assert entry.runtime_data.payload()["fit_done"] is True
    before = entry.runtime_data.calibrator.to_dict()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.calibrator.to_dict() == before
    assert value(hass, entry, "sensor", "calibration_samples") == "7"


async def test_not_enough_history_keeps_the_options(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    enable_custom_integrations: None,
    freezer,
) -> None:
    """With fewer than 5 closures the parameters fitted from closures stay at their options."""
    await record_fixture(hass, freezer, "long_shower")
    entry = await setup_entry(hass, week_options())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert int(value(hass, entry, "sensor", "calibration_samples")) < 5
    assert value(hass, entry, "sensor", "other_hot_share") == "0.2"
    assert value(hass, entry, "sensor", "startup_energy") == "0.0"
    for key in ("other_hot_share", "startup_energy"):
        state = hass.states.get(entity_id(hass, entry, "sensor", key))
        assert state is not None
        assert state.attributes["source"] == "option"


async def test_recalibrate_refits_but_keeps_locks_and_the_button_value(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    enable_custom_integrations: None,
    freezer,
) -> None:
    """A recalibrate keeps a locked share at its option and the usable fraction from the button."""
    await record_fixture(hass, freezer, "week")
    options = week_options() | {
        CONF_LOCKS: ["other_hot_share"],
        "other_hot_share": 0.25,
    }
    entry = await setup_entry(hass, options)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, "sensor", "other_hot_share") == "0.25"
    estimator = entry.runtime_data
    estimator.calibrator.values["usable_fraction"] = 0.72
    estimator.calibrator.sources["usable_fraction"] = "learned"
    estimator.calibrator.values["startup_energy"] = 0.5
    estimator.calibrator.sources["startup_energy"] = "learned"
    await hass.services.async_call(
        DOMAIN,
        "recalibrate",
        {"entity_id": entity_id(hass, entry, "sensor", "tank_litres"), "days": 14},
        blocking=True,
    )
    assert value(hass, entry, "sensor", "other_hot_share") == "0.25"
    assert value(hass, entry, "sensor", "usable_fraction") == "72.0"
    data = json.loads((FIXTURES / "week.json").read_text("utf-8"))
    fit = setup_fit(
        history_from_fixture(data),
        TankConfig.from_options(options).options,
        locks=["other_hot_share"],
    )
    assert float(value(hass, entry, "sensor", "startup_energy")) == pytest.approx(
        fit.parameters["startup_energy"][0], abs=0.02
    )
    assert value(hass, entry, "sensor", "calibration_samples") == "7"
    state = hass.states.get(entity_id(hass, entry, "sensor", "other_hot_share"))
    assert state is not None
    assert state.attributes["source"] == "locked"


async def test_reading_the_recorder_converts_units(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    enable_custom_integrations: None,
    freezer,
) -> None:
    """Fahrenheit becomes Celsius, watt-hours kilowatt-hours; the meter keeps its unit."""
    freezer.move_to("2026-10-10T00:00:00+00:00")
    hass.states.async_set(TANK, "131.0", {"unit_of_measurement": "°F"})
    hass.states.async_set(ENERGY, "10000", {"unit_of_measurement": "Wh"})
    hass.states.async_set(METER, "5.5", {"unit_of_measurement": "m³"})
    hass.states.async_set(HEATING, "on")
    freezer.move_to("2026-10-10T01:00:00+00:00")
    hass.states.async_set(TANK, "unavailable")
    hass.states.async_set(HEATING, "off")
    await async_wait_recording_done(hass)
    freezer.move_to("2026-10-10T02:00:00+00:00")
    end = dt_util.utcnow()
    config = TankConfig.from_options(FULL_OPTIONS)
    history = await async_read_history(hass, config, end - timedelta(days=30), end)
    series = {s.entity_id: s for s in history.series}
    assert [state for _, state in series[TANK].states] == ["55.0", "unavailable"]
    assert [state for _, state in series[ENERGY].states] == ["10.0"]
    assert [state for _, state in series[HEATING].states] == ["on", "off"]
    assert series[METER].unit == "m³"
    assert history.start == datetime(2026, 10, 10, tzinfo=dt_util.UTC)
    assert history.end == end


async def test_no_recorder_means_no_setup_fit(hass: HomeAssistant, freezer) -> None:
    """Without the recorder the entry still runs on the option values."""
    rig = await Rig.start(hass, freezer)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert rig.read("sensor", "calibration_samples") == "0"
    assert rig.read("sensor", "other_hot_share") == "0.2"
    assert rig.entry.runtime_data.payload()["fit_done"] is False


async def draw_one_litre_and_wait(rig: Rig, minutes: float = 5.0) -> float:
    """Draw 1 L, wait until the session is over, and return the cold fraction at its end."""
    await rig.set(METER, "100.001", after=30)
    await rig.tick(minutes)
    record = rig.entry.runtime_data.model.last_draw_end(dt_util.utcnow())
    assert record is not None
    return record.cold_fraction


async def part_drawn(rig: Rig) -> None:
    """Set the tank to 45 C on average, charged at 55 C: the tank sensor (20 C) is under T_ch."""
    await rig.hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(rig.hass, rig.entry, "sensor", "tank_litres"),
            "tank_average": 45,
            "charged_temperature": 55,
        },
        blocking=True,
    )


async def press_hot_water_ran_out(rig: Rig) -> None:
    """Press the "Hot water ran out" button of the rig's entry."""
    await rig.hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(rig.hass, rig.entry, "button", "hot_water_ran_out")},
        blocking=True,
    )


def notifications(hass: HomeAssistant) -> dict[str, dict]:
    """Collect the persistent notifications that are shown from now on, by notification ID."""
    shown: dict[str, dict] = {}

    @callback
    def collect(update_type: UpdateType, current: dict) -> None:
        if update_type in (UpdateType.ADDED, UpdateType.UPDATED):
            shown.update(current)
        elif update_type == UpdateType.REMOVED:
            for key in current:
                shown.pop(key, None)

    persistent_notification.async_register_callback(hass, collect)
    return shown


async def test_hot_water_ran_out_accepted(hass: HomeAssistant, freezer) -> None:
    """A press after a draw that ended at a cold fraction near 0.72 learns it and empties the tank."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    estimator = rig.entry.runtime_data
    shown = notifications(hass)
    t_cold = estimator.model.t_cold
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, rig.entry, "sensor", "tank_litres"),
            "tank_average": 55 - 0.72 * (55 - t_cold),
            "charged_temperature": 55,
        },
        blocking=True,
    )
    fraction = await draw_one_litre_and_wait(rig)
    assert fraction == pytest.approx(0.72, abs=0.01)
    assert rig.read("sensor", "usable_fraction") == "85.0"
    assert float(rig.read("sensor", "tank_litres")) > 0
    await press_hot_water_ran_out(rig)
    assert rig.read("sensor", "usable_fraction") == str(round(fraction * 100, 1))
    assert rig.read("sensor", "tank_litres") == "0"
    assert rig.read("sensor", "percent_charged") == "0"
    state = hass.states.get(entity_id(hass, rig.entry, "sensor", "usable_fraction"))
    assert state is not None
    assert state.attributes["source"] == "learned"
    assert not shown
    (event,) = [
        e for e in estimator.model.events if e.kind == EventKind.HOT_WATER_RAN_OUT
    ]
    assert event.change["result"] == "accepted"
    assert event.change["cold_fraction"] == pytest.approx(fraction)


async def test_a_rejected_press_changes_nothing_and_says_why(
    hass: HomeAssistant, freezer
) -> None:
    """With no draw in the last 20 minutes, a press shows a notification and changes nothing."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    estimator = rig.entry.runtime_data
    shown = notifications(hass)
    await draw_one_litre_and_wait(rig, minutes=25)
    model_before = estimator.model.to_dict()
    calibration_before = estimator.calibrator.to_dict()
    await press_hot_water_ran_out(rig)
    assert estimator.model.to_dict() == model_before
    assert estimator.calibrator.to_dict() == calibration_before
    assert rig.read("sensor", "usable_fraction") == "85.0"
    (notification,) = shown.values()
    assert notification["notification_id"] == (
        f"{DOMAIN}_{rig.entry.entry_id}_hot_water_ran_out"
    )
    assert notification["title"] == "Hot water"
    assert notification["message"] == (
        "Ignored: no water was drawn in the last 20 minutes."
    )
    (event,) = [
        e for e in estimator.model.events if e.kind == EventKind.HOT_WATER_RAN_OUT
    ]
    assert event.change == {
        "result": "rejected",
        "reason": "no_recent_draw",
        "minutes": 20,
    }


async def test_a_press_with_the_sensor_still_hot_names_the_reading(
    hass: HomeAssistant, freezer
) -> None:
    """The notification says what the tank sensor read when the last draw ended."""
    rig = await Rig.start(hass, freezer, states={TANK: "55.8"})
    shown = notifications(hass)
    await draw_one_litre_and_wait(rig)
    await press_hot_water_ran_out(rig)
    (notification,) = shown.values()
    assert notification["message"] == (
        "Ignored: the tank sensor still read 55.8 C when the last draw ended, "
        "so the tank was not empty."
    )
    assert rig.read("sensor", "usable_fraction") == "85.0"


async def test_repeated_rejected_presses_replace_the_notification(
    hass: HomeAssistant, freezer
) -> None:
    """One notification per tank: a second rejected press replaces the first, an accepted one removes it."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    shown = notifications(hass)
    await press_hot_water_ran_out(rig)
    await press_hot_water_ran_out(rig)
    assert len(shown) == 1
    await part_drawn(rig)
    await draw_one_litre_and_wait(rig)
    await press_hot_water_ran_out(rig)
    assert not shown


async def test_the_button_value_is_saved(hass: HomeAssistant, freezer) -> None:
    """The usable fraction from the button survives a reload."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    await part_drawn(rig)
    await draw_one_litre_and_wait(rig)
    await press_hot_water_ran_out(rig)
    learned = rig.read("sensor", "usable_fraction")
    assert learned != "85.0"
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert rig.read("sensor", "usable_fraction") == learned
    assert rig.entry.runtime_data.calibrator.source_of("usable_fraction") == "learned"


async def test_restart_keeps_the_learned_share(hass: HomeAssistant, freezer) -> None:
    """A share of 0.22 learned before a restart is the share in use after it."""
    rig = await Rig.start(hass, freezer)
    calibrator = rig.entry.runtime_data.calibrator
    calibrator.values["other_hot_share"] = 0.22
    calibrator.sources["other_hot_share"] = "learned"
    rig.entry.runtime_data.model.set_options(calibrator.options)
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert rig.read("sensor", "other_hot_share") == "0.22"
    assert rig.entry.runtime_data.model.options.other_hot_share == 0.22


async def test_removing_a_lock_discards_the_value_learned_before_it(
    hass: HomeAssistant, freezer
) -> None:
    """A locked share uses its option; unlocking it again does not bring the old value back."""
    rig = await Rig.start(hass, freezer)
    calibrator = rig.entry.runtime_data.calibrator
    calibrator.values["other_hot_share"] = 0.22
    calibrator.sources["other_hot_share"] = "learned"
    options = rig.entry.options
    entry: MockConfigEntry = rig.entry
    hass.config_entries.async_update_entry(
        entry,
        options={**options, CONF_LOCKS: ["other_hot_share"], "other_hot_share": 0.25},
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert rig.read("sensor", "other_hot_share") == "0.25"
    assert entry.runtime_data.calibrator.source_of("other_hot_share") == "locked"
    hass.config_entries.async_update_entry(
        entry, options={k: v for k, v in entry.options.items() if k != CONF_LOCKS}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert rig.read("sensor", "other_hot_share") == "0.25"
    assert entry.runtime_data.calibrator.source_of("other_hot_share") == "option"


async def test_removing_the_entry_deletes_its_store(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """The calibration store of a removed tank is deleted."""
    rig = await Rig.start(hass, freezer)
    key = f"{DOMAIN}.{rig.entry.entry_id}"
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    assert key in hass_storage
    assert hass_storage[key]["data"]["fit_done"] is False
    await hass.config_entries.async_remove(rig.entry.entry_id)
    assert key not in hass_storage


def week_history() -> History:
    """Return the week fixture as a history."""
    return history_from_fixture(json.loads((FIXTURES / "week.json").read_text("utf-8")))


WEEK_END = "2026-10-30T12:30:00+00:00"


def with_week_history(hass: HomeAssistant):
    """Patch the recorder read to return the week fixture, cut to the days asked for."""
    hass.config.components.add("recorder")
    history = week_history()

    async def read(_hass, _config, start, _end):
        return history.since(start)

    return patch(
        "custom_components.hot_water_tank_estimator.estimator.async_read_history",
        side_effect=read,
    )


class HeldFit:
    """Holds a fit while it reads its history, until the test releases it.

    The test environment runs executor jobs inline, so the hold is in the (async) read.
    `log` shows the order of reads and fits.
    """

    def __init__(self, *, hold: bool = True) -> None:
        """Create the gate. With `hold`, the next read waits for `release`."""
        self.hold = hold
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.log: list[str] = []
        self.history = week_history()

    async def read(self, _hass, _config, start, _end) -> History:
        """Return the week fixture, after the gate if it holds."""
        self.log.append("read")
        if self.hold:
            self.hold = False
            self.started.set()
            await self.release.wait()
        return self.history.since(start)

    def fit(self, *args, **kwargs):
        """Run the setup fit."""
        self.log.append("fit")
        return setup_fit(*args, **kwargs)


def held_fit(*, hold: bool = True) -> tuple[HeldFit, Callable]:
    """Return the gate and a context manager that installs it."""
    gate = HeldFit(hold=hold)
    module = "custom_components.hot_water_tank_estimator.estimator"

    @contextmanager
    def install(hass: HomeAssistant):
        hass.config.components.add("recorder")
        with (
            patch(f"{module}.async_read_history", side_effect=gate.read),
            patch(f"{module}.setup_fit", side_effect=gate.fit),
        ):
            yield

    return gate, install


async def start_while_fitting(hass: HomeAssistant, gate: HeldFit) -> MockConfigEntry:
    """Set up the week entry and wait until its first fit is running (and held)."""
    entry = MockConfigEntry(domain=DOMAIN, title="Hot water", options=week_options())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await gate.started.wait()
    return entry


async def test_recalibrate_after_moving_the_sensor(
    hass: HomeAssistant, freezer
) -> None:
    """After the sensor height changes, a recalibrate with 3 days refits from the last 3 days."""
    freezer.move_to(WEEK_END)
    with with_week_history(hass):
        entry = await setup_entry(hass, week_options())
        await hass.async_block_till_done(wait_background_tasks=True)
        assert value(hass, entry, "sensor", "calibration_samples") == "7"

        options = {**entry.options, CONF_SENSOR_HEIGHT: 65.0}
        hass.config_entries.async_update_entry(entry, options=options)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.model.options.sensor_height == pytest.approx(0.65)
        assert value(hass, entry, "sensor", "calibration_samples") == "7"

        await hass.services.async_call(
            DOMAIN,
            "recalibrate",
            {"entity_id": entity_id(hass, entry, "sensor", "tank_litres"), "days": 3},
            blocking=True,
        )

    fit = setup_fit(
        week_history().last_days(3), TankConfig.from_options(options).options
    )
    assert value(hass, entry, "sensor", "calibration_samples") == str(
        len(fit.intervals)
    )
    assert len(fit.intervals) < 7
    for key in (
        "other_hot_share",
        "startup_energy",
        "loss_coefficient",
        "thermocline_width",
    ):
        expected, source = fit.parameters[key]
        scale = 100 if key == "thermocline_width" else 1
        assert float(value(hass, entry, "sensor", key)) == pytest.approx(
            expected * scale, rel=0.01, abs=1e-4
        )
        state = hass.states.get(entity_id(hass, entry, "sensor", key))
        assert state is not None
        assert state.attributes["source"] == source


async def test_a_button_press_during_a_fit_is_kept(
    hass: HomeAssistant, freezer
) -> None:
    """The usable fraction from a press made while the fit ran is still in use afterwards."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        for reading in ("100.000", "100.001"):
            hass.states.async_set(METER, reading, {"unit_of_measurement": "m\u00b3"})
            await hass.async_block_till_done()
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, entry, "button", "hot_water_ran_out")},
            blocking=True,
        )
        assert value(hass, entry, "sensor", "usable_fraction") == "50.0"
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, "sensor", "calibration_samples") == "7"
    assert value(hass, entry, "sensor", "usable_fraction") == "50.0"
    state = hass.states.get(entity_id(hass, entry, "sensor", "usable_fraction"))
    assert state is not None
    assert state.attributes["source"] == "learned"
    assert entry.runtime_data.model.options.usable_fraction == 0.5


async def test_a_manual_reset_during_a_fit_stays_excluded(
    hass: HomeAssistant, freezer
) -> None:
    """The interval that holds a set_tank_state made during a fit is still not a closure."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        await hass.services.async_call(
            DOMAIN,
            "set_tank_state",
            {
                "entity_id": entity_id(hass, entry, "sensor", "tank_litres"),
                "tank_average": 40,
                "charged_temperature": 55,
            },
            blocking=True,
        )
        assert entry.runtime_data.calibrator.to_dict()["unknown_start"] is not None
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, "sensor", "calibration_samples") == "7"
    assert (
        entry.runtime_data.calibrator.to_dict()["unknown_start"] == "after_manual_reset"
    )


async def test_two_recalibrates_run_one_after_the_other(
    hass: HomeAssistant, freezer
) -> None:
    """A recalibrate during a running fit waits for it, then runs."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        task = asyncio.ensure_future(
            hass.services.async_call(
                DOMAIN,
                "recalibrate",
                {"entity_id": entity_id(hass, entry, "sensor", "tank_litres")},
                blocking=True,
            )
        )
        for _ in range(30):  # the clock is frozen, so a timed sleep would not return
            await asyncio.sleep(0)
        assert not task.done()
        assert gate.log == ["read"]
        gate.release.set()
        await task
        await hass.async_block_till_done(wait_background_tasks=True)
    assert gate.log == ["read", "fit", "read", "fit"]
    assert value(hass, entry, "sensor", "calibration_samples") == "7"


async def test_a_fit_that_ends_after_unload_is_dropped(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """A fit that finishes after the entry was unloaded neither applies nor saves."""
    gate, install = held_fit(hold=False)
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await setup_entry(hass, week_options())
        await hass.async_block_till_done(wait_background_tasks=True)
        estimator = entry.runtime_data
        calibrator = estimator.calibrator
        gate.hold = True
        task = asyncio.ensure_future(estimator.async_setup_fit())
        await gate.started.wait()
        assert await hass.config_entries.async_unload(entry.entry_id)
        gate.release.set()
        assert await task is None
    assert estimator.calibrator is calibrator
    assert gate.log == ["read", "fit", "read"]
    # Nothing is saved after the unload either, however long the delay passes.
    key = f"{DOMAIN}.{entry.entry_id}"
    saved = json.dumps(hass_storage[key], sort_keys=True)
    freezer.tick(timedelta(seconds=120))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert json.dumps(hass_storage[key], sort_keys=True) == saved


async def run_heating(rig: Rig, kwh: float) -> float:
    """A heating run of 20 minutes with 0.4 kWh a minute. Returns the counter at its end."""
    await rig.set(HEATING, "on", after=60)
    await rig.set("sensor.flow_temperature", "57.0")
    await rig.set("sensor.return_temperature", "55.0")
    for step in range(1, 21):
        await rig.set(ENERGY, f"{kwh + 0.4 * step:.1f}", after=60)
    await rig.set(HEATING, "off", after=30)
    return kwh + 8.0


async def test_live_learning_at_each_charge(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """Runs end, the counter lag passes, and the closures are counted and stored."""
    rig = await Rig.start(hass, freezer)
    estimator = rig.entry.runtime_data
    kwh = await run_heating(rig, 10.0)
    assert estimator.calibrator.closures == []  # waits for the counter lag
    await rig.tick(11)
    # The first charge of a live model closes nothing: it starts from the sensor reading.
    assert [c.status for c in estimator.calibrator.closures] == [SENSOR_START]
    assert rig.read("sensor", "calibration_samples") == "0"

    await rig.set("sensor.water_meter", "100.030", after=600)
    await run_heating(rig, kwh)
    await rig.tick(11)
    statuses = [c.status for c in estimator.calibrator.closures]
    assert statuses == [SENSOR_START, CLOSURE]
    assert rig.read("sensor", "calibration_samples") == "1"
    assert rig.read("sensor", "last_charge_error") != "unknown"
    assert rig.read("sensor", "mean_charge_error") != "unknown"

    # The first sensor drop after the charge gives a width estimate.
    assert estimator.calibrator.width_estimates == []
    await rig.set("sensor.tank_temperature", "50.0", after=60)
    assert len(estimator.calibrator.width_estimates) == 1

    # The store is written after its delay.
    key = f"{DOMAIN}.{rig.entry.entry_id}"
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    saved = hass_storage[key]["data"]
    assert len(saved["calibrator"]["closures"]) == 2
    assert len(saved["calibrator"]["width_estimates"]) == 1
    assert saved["model"]["t_ch"] == pytest.approx(estimator.model.t_ch)


async def test_first_run_after_a_new_entry(hass: HomeAssistant, freezer) -> None:
    """A new entry starts at the sensor reading: its first run is a sensor start, then closures."""
    rig = await Rig.start(hass, freezer)
    estimator = rig.entry.runtime_data
    assert rig.read("sensor", "calibration_samples") == "0"

    kwh = await run_heating(rig, 10.0)
    await rig.tick(11)
    assert [c.status for c in estimator.calibrator.closures] == [SENSOR_START]
    assert rig.read("sensor", "calibration_samples") == "0"

    await run_heating(rig, kwh)
    await rig.tick(11)
    assert [c.status for c in estimator.calibrator.closures] == [SENSOR_START, CLOSURE]
    assert rig.read("sensor", "calibration_samples") == "1"


async def test_continuous_inputs_do_not_postpone_the_save(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """With an input every 30 s the store is still written about once a minute."""
    rig = await Rig.start(hass, freezer)
    key = f"{DOMAIN}.{rig.entry.entry_id}"
    estimator = rig.entry.runtime_data
    # Let the save requested at the start go first, then count the writes from here on.
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert key in hass_storage
    del hass_storage[key]
    writes = 0
    real_payload = estimator.payload

    def counting_payload() -> dict:
        nonlocal writes
        writes += 1
        return real_payload()

    with patch.object(estimator, "payload", counting_payload):
        written: list[int] = []
        for step in range(20):  # 10 minutes, an input every 30 s
            await rig.set(HUMIDITY, f"{50 + step}", after=30 if step else 0)
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
            written.append(writes)
    assert written[0] == 0 and written[1] == 0  # nothing within the first 30 s
    assert written[3] >= 1, written  # written within about 60 s of the first input
    assert key in hass_storage
    first = next(i for i, count in enumerate(written) if count)
    assert written[first + 4] >= 2  # and again about a minute later
    assert writes <= 11  # never more than once a minute


async def test_after_a_week_of_use(hass: HomeAssistant, freezer) -> None:
    """With 9 charge closures the samples, the errors and the sources are shown."""
    rig = await Rig.start(hass, freezer)
    estimator = rig.entry.runtime_data
    template = setup_fit(
        week_history(), TankConfig.from_options(week_options()).options
    ).intervals
    closures = [*template, *template[:2]]
    for closure in closures:
        estimator.calibrator.add_closure(closure)
    async_dispatcher_send(hass, estimator.signal)
    await hass.async_block_till_done()

    assert estimator.calibrator.sample_count == 9
    assert rig.read("sensor", "calibration_samples") == "9"
    errors = [c.error for c in closures]
    assert float(rig.read("sensor", "last_charge_error")) == pytest.approx(
        errors[-1], abs=0.01
    )
    assert float(rig.read("sensor", "mean_charge_error")) == pytest.approx(
        sum(abs(e) for e in errors) / 9, abs=0.01
    )
    sources = set()
    for key in (
        "other_hot_share",
        "startup_energy",
        "loss_coefficient",
        "thermocline_width",
        "usable_fraction",
    ):
        state = hass.states.get(entity_id(hass, rig.entry, "sensor", key))
        assert state is not None
        expected = estimator.calibrator.source_of(key)
        assert state.attributes["source"] == expected
        sources.add(expected)
    assert "learned" in sources
    assert "option" in sources


def test_a_text_with_an_unknown_placeholder_still_formats() -> None:
    """A translation that names a value the press does not give keeps the placeholder."""
    text = "Ignored: {sensor} C and {other}."
    assert text.format_map(_Tolerant({"sensor": "55.8"})) == (
        "Ignored: 55.8 C and {other}."
    )


async def press_undo(rig: Rig) -> None:
    """Press the "Undo hot water ran out" button of the rig's entry."""
    await rig.hass.services.async_call(
        "button",
        "press",
        {
            "entity_id": entity_id(
                rig.hass, rig.entry, "button", "undo_hot_water_ran_out"
            )
        },
        blocking=True,
    )


def undo_state(rig: Rig) -> str:
    """Return the state of the undo button: unavailable, or the time of its last press."""
    state = rig.hass.states.get(
        entity_id(rig.hass, rig.entry, "button", "undo_hot_water_ran_out")
    )
    assert state is not None
    return state.state


async def pressed_at_the_floor(rig: Rig) -> float:
    """Draw 1 L from a tank at a cold fraction of 0.4, press, and return T_avg before the press.

    The tank sensor must read well above the average the draw leaves (the tests give it 35 C),
    or its bound would raise the cold fraction above the usable fraction's floor.
    """
    estimator = rig.entry.runtime_data
    t_cold = estimator.model.t_cold
    await rig.hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(rig.hass, rig.entry, "sensor", "tank_litres"),
            "tank_average": 55 - 0.4 * (55 - t_cold),
            "charged_temperature": 55,
        },
        blocking=True,
    )
    await draw_one_litre_and_wait(rig)
    before = estimator.model.t_avg
    await press_hot_water_ran_out(rig)
    return before


async def test_the_undo_button_follows_the_press(hass: HomeAssistant, freezer) -> None:
    """Unavailable before a press, available after an accepted one, unavailable after an undo."""
    rig = await Rig.start(hass, freezer, states={TANK: "35.0"})
    estimator = rig.entry.runtime_data
    assert undo_state(rig) == "unavailable"
    before = await pressed_at_the_floor(rig)
    assert estimator.model.t_avg < before
    assert rig.read("sensor", "usable_fraction") == "50.0"
    assert undo_state(rig) != "unavailable"
    await press_undo(rig)
    assert rig.read("sensor", "usable_fraction") == "85.0"
    assert estimator.model.t_avg == pytest.approx(before)
    assert undo_state(rig) == "unavailable"
    state = hass.states.get(entity_id(hass, rig.entry, "sensor", "usable_fraction"))
    assert state is not None
    assert state.attributes["source"] == "option"
    event = [
        e for e in estimator.model.events if e.kind == EventKind.HOT_WATER_RAN_OUT
    ][-1]
    assert event.change["result"] == "undone"
    assert event.change["usable_fraction"] == 0.85
    assert event.change["rise"] > 0
    assert event.change["after_reset"] is False
    # Nothing is left to undo: a late call explains it.
    with pytest.raises(ServiceValidationError):
        await estimator.async_undo_hot_water_ran_out()


async def test_the_undo_button_is_available_after_a_restart(
    hass: HomeAssistant, freezer
) -> None:
    """The record is saved: after a reload the button is available and undo restores u."""
    rig = await Rig.start(hass, freezer, states={TANK: "35.0"})
    before = await pressed_at_the_floor(rig)
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert undo_state(rig) != "unavailable"
    await press_undo(rig)
    assert rig.read("sensor", "usable_fraction") == "85.0"
    assert rig.entry.runtime_data.model.t_avg == pytest.approx(before)


async def test_the_undo_button_goes_when_its_time_runs_out(
    hass: HomeAssistant, freezer
) -> None:
    """A reset after the press starts the 24 hours; the 5-minute tick then removes the button."""
    rig = await Rig.start(hass, freezer, states={TANK: "35.0"})
    await pressed_at_the_floor(rig)
    await rig.tick(minutes=1)
    await part_drawn(rig)  # a set_tank_state: undo now restores only u
    assert undo_state(rig) != "unavailable"
    await rig.tick(minutes=23 * 60)
    assert undo_state(rig) != "unavailable"
    await rig.tick(minutes=2 * 60)
    assert undo_state(rig) == "unavailable"
    assert rig.entry.runtime_data.calibrator.undo_record is None


async def test_a_rejected_press_leaves_the_undo_button_unavailable(
    hass: HomeAssistant, freezer
) -> None:
    """Only an accepted press can be undone."""
    rig = await Rig.start(hass, freezer, states={TANK: "35.0"})
    await draw_one_litre_and_wait(rig, minutes=25)
    await press_hot_water_ran_out(rig)
    assert undo_state(rig) == "unavailable"


async def test_an_undo_during_a_fit_stays_undone(hass: HomeAssistant, freezer) -> None:
    """A press made before a fit and undone while it ran: the fit does not bring u or the record back."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        for reading in ("100.000", "100.001"):
            hass.states.async_set(METER, reading, {"unit_of_measurement": "m³"})
            await hass.async_block_till_done()
        # The first fit is held: finish it, press, then hold the next one with a recalibrate.
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, entry, "button", "hot_water_ran_out")},
            blocking=True,
        )
        assert value(hass, entry, "sensor", "usable_fraction") == "50.0"
        gate.hold = True
        gate.release.clear()
        gate.started.clear()
        task = hass.async_create_task(entry.runtime_data.async_setup_fit())
        await gate.started.wait()
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, entry, "button", "undo_hot_water_ran_out")},
            blocking=True,
        )
        assert value(hass, entry, "sensor", "usable_fraction") == "85.0"
        gate.release.set()
        await task
        await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, "sensor", "usable_fraction") == "85.0"
    assert "usable_fraction" not in entry.runtime_data.calibrator.values
    assert entry.runtime_data.calibrator.undo_record is None
    state = hass.states.get(entity_id(hass, entry, "button", "undo_hot_water_ran_out"))
    assert state is not None
    assert state.state == "unavailable"


async def test_a_press_during_a_fit_keeps_its_undo(
    hass: HomeAssistant, freezer
) -> None:
    """The undo record of a press made while the fit ran survives the fit, and the button is available."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        for reading in ("100.000", "100.001"):
            hass.states.async_set(METER, reading, {"unit_of_measurement": "m³"})
            await hass.async_block_till_done()
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, entry, "button", "hot_water_ran_out")},
            blocking=True,
        )
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.calibrator.undo_record is not None
    state = hass.states.get(entity_id(hass, entry, "button", "undo_hot_water_ran_out"))
    assert state is not None
    assert state.state != "unavailable"
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, entry, "button", "undo_hot_water_ran_out")},
        blocking=True,
    )
    assert value(hass, entry, "sensor", "usable_fraction") == "85.0"


async def test_a_discarded_model_drops_the_undo_record(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    """When the stored model is unusable, the undo record cannot be applied to the fresh one."""
    rig = await Rig.start(hass, freezer, states={TANK: "35.0"})
    await pressed_at_the_floor(rig)
    estimator = rig.entry.runtime_data
    assert estimator.calibrator.undo_record is not None
    saved = estimator.payload()
    saved["model"] = {"broken": True}
    hass_storage[f"{DOMAIN}.{rig.entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{rig.entry.entry_id}",
        "data": json.loads(json.dumps(saved)),
    }
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    hass_storage[f"{DOMAIN}.{rig.entry.entry_id}"]["data"] = json.loads(
        json.dumps(saved)
    )
    assert await hass.config_entries.async_setup(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert not rig.entry.runtime_data.model_restored
    assert rig.entry.runtime_data.calibrator.undo_record is None
    assert undo_state(rig) == "unavailable"
