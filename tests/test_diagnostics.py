"""Tests for the diagnostics (task 5.8)."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from custom_components.hot_water_tank_estimator.const import DIAGNOSTIC_EVENTS, DOMAIN
from custom_components.hot_water_tank_estimator.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.hot_water_tank_estimator.model import ModelOptions
from custom_components.hot_water_tank_estimator.setup_fit import (
    history_from_fixture,
    setup_fit,
)
from homeassistant.core import HomeAssistant

from .common import ENERGY, FLOW, HEATING, HUMIDITY, METER, RETURN, TANK, Rig, entity_id

FIXTURES = Path(__file__).parent / "fixtures"


async def part_drawn(hass: HomeAssistant, rig: Rig) -> None:
    """Set the tank to 45 C on average, charged at 55 C: the tank sensor (20 C) is under T_ch."""
    await hass.services.async_call(
        DOMAIN,
        "set_tank_state",
        {
            "entity_id": entity_id(hass, rig.entry, "sensor", "tank_litres"),
            "tank_average": 45,
            "charged_temperature": 55,
        },
        blocking=True,
    )


async def press(hass: HomeAssistant, rig: Rig) -> None:
    """Press the "Hot water ran out" button."""
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, rig.entry, "button", "hot_water_ran_out")},
        blocking=True,
    )


async def test_download_diagnostics(hass: HomeAssistant, freezer) -> None:
    """The file has the options, the state, the sources, the events and the calibration."""
    rig = await Rig.start(hass, freezer)
    await rig.set(METER, "100.010", after=60)
    await rig.set(HUMIDITY, "70.0", after=30)
    hass.states.async_set(RETURN, "unavailable")
    await hass.async_block_till_done()

    data = await async_get_config_entry_diagnostics(hass, rig.entry)

    json.dumps(data)  # the file must be JSON
    assert set(data) == {
        "options",
        "state",
        "sources",
        "repair_issues",
        "events",
        "calibration",
    }
    assert data["options"] == dict(rig.entry.options)
    state = data["state"]
    assert state["t_avg"] == rig.entry.runtime_data.model.t_avg
    assert state["t_ch"] == rig.entry.runtime_data.model.t_ch
    assert {
        "t_cold",
        "t_ambient",
        "cold_fraction",
        "outputs",
        "heating",
        "shower_detected",
        "model",
    } <= set(state)
    assert set(state["outputs"]) == {
        "tank_litres",
        "shower_litres",
        "percent_charged",
        "shower_minutes",
    }
    assert state["model"]["version"] == 1
    assert data["sources"][RETURN] is False
    assert data["sources"][METER] is True
    assert set(data["sources"]) == {
        TANK,
        METER,
        ENERGY,
        HEATING,
        FLOW,
        RETURN,
        HUMIDITY,
    }
    assert data["events"]
    event = data["events"][-1]
    assert set(event) == {
        "time",
        "kind",
        "change",
        "t_avg_before",
        "t_avg_after",
        "t_ch_before",
        "t_ch_after",
    }
    assert {e["kind"] for e in data["events"]} >= {"draw"}
    calibration = data["calibration"]
    assert set(calibration) == {
        "parameters",
        "samples",
        "last_error",
        "mean_abs_error",
        "closures",
        "quiet_estimates",
        "width_estimates",
        "shower_flow_history",
        "undo",
    }
    assert calibration["undo"] is None
    assert calibration["shower_flow_history"] == []
    assert set(calibration["parameters"]) == {
        "other_hot_share",
        "startup_energy",
        "loss_coefficient",
        "thermocline_width",
        "usable_fraction",
        "shower_flow",
    }
    assert calibration["parameters"]["other_hot_share"] == {
        "value": 0.2,
        "source": "option",
    }


async def test_only_the_last_100_events(hass: HomeAssistant, freezer) -> None:
    """The events are limited to the most recent 100."""
    rig = await Rig.start(hass, freezer)
    for step in range(1, 130):
        await rig.set(METER, f"{100 + 0.001 * step:.3f}", after=120)
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    assert len(data["events"]) == DIAGNOSTIC_EVENTS
    times = [e["time"] for e in data["events"]]
    assert times == sorted(times)


async def test_a_calibration_event_appears(hass: HomeAssistant, freezer) -> None:
    """A button press logs a calibration event with the old and new value and the source."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    await part_drawn(hass, rig)
    await rig.set(METER, "100.001", after=30)
    await rig.tick(5)
    await press(hass, rig)
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    events = [e for e in data["events"] if e["kind"] == "calibration"]
    assert len(events) == 1
    change = events[0]["change"]
    assert change["trigger"] == "hot_water_ran_out"
    (press_event,) = [e for e in data["events"] if e["kind"] == "hot_water_ran_out"]
    assert change["parameters"]["usable_fraction"] == {
        "old": 0.85,
        "new": pytest.approx(press_event["change"]["cold_fraction"]),
        "source": "learned",
    }
    # The manual reset is an excluded interval for the next closure; closures are listed.
    assert isinstance(data["calibration"]["closures"], list)


async def test_an_accepted_press_is_in_the_events(hass: HomeAssistant, freezer) -> None:
    """An accepted press logs a hot water ran out event with the draw end and the figures."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    await part_drawn(hass, rig)
    await rig.set(METER, "100.001", after=30)
    await rig.tick(5)
    await press(hass, rig)
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    (event,) = [e for e in data["events"] if e["kind"] == "hot_water_ran_out"]
    assert event["change"]["result"] == "accepted"
    assert event["change"]["usable_fraction"] == pytest.approx(
        event["change"]["cold_fraction"]
    )
    assert set(event["change"]) >= {"draw_end", "cold_fraction", "drop"}
    undo = data["calibration"]["undo"]
    assert undo["drop"] == event["change"]["drop"]
    assert undo["usable"] is None
    json.dumps(data)


async def test_rejected_press_in_the_diagnostics(hass: HomeAssistant, freezer) -> None:
    """A press with no draw in the last 20 minutes is an event marked rejected, with its reason."""
    rig = await Rig.start(hass, freezer, states={TANK: "20.0"})
    await press(hass, rig)
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    (event,) = [e for e in data["events"] if e["kind"] == "hot_water_ran_out"]
    assert event["change"]["result"] == "rejected"
    assert event["change"]["reason"] == "no_recent_draw"
    assert event["t_avg_before"] == event["t_avg_after"]
    assert data["calibration"]["parameters"]["usable_fraction"]["source"] == "option"
    assert data["state"]["model"]["draw_end"] is None
    json.dumps(data)


async def test_excluded_closures_are_listed_with_their_reason(
    hass: HomeAssistant, freezer
) -> None:
    """An excluded closure appears in the diagnostics with its status and reason."""
    rig = await Rig.start(hass, freezer)
    calibrator = rig.entry.runtime_data.calibrator
    template = setup_fit(
        history_from_fixture(json.loads((FIXTURES / "week.json").read_text("utf-8"))),
        ModelOptions(volume=281.0),
    ).closures[1]
    calibrator.add_closure(replace(template, status="excluded", reason="short_run"))
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    closures = data["calibration"]["closures"]
    assert [(c["status"], c["reason"]) for c in closures] == [("excluded", "short_run")]


async def test_silent_humidity_sensor_in_the_diagnostics(
    hass: HomeAssistant, freezer
) -> None:
    """Integration-setup scenario "Silent humidity sensor in the diagnostics"."""
    rig = await Rig.start(hass, freezer)  # the sensor reported at 10:00
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    assert data["state"]["humidity"] == {
        "sensors": {
            HUMIDITY: {
                "last_report": "2026-10-15T10:00:00+00:00",
                "unavailable": False,
                "silent": False,
            }
        },
        "fallback": False,
    }
    assert data["repair_issues"] == []
    await rig.tick(minutes=180)  # 3 hours without a report, silence time 2 hours
    data = await async_get_config_entry_diagnostics(hass, rig.entry)
    json.dumps(data)
    assert data["state"]["humidity"] == {
        "sensors": {
            HUMIDITY: {
                "last_report": "2026-10-15T10:00:00+00:00",
                "unavailable": False,
                "silent": True,
            }
        },
        "fallback": True,
    }
    assert data["state"]["model"]["humidity_reports"][HUMIDITY]["last_report"] == (
        "2026-10-15T10:00:00+00:00"
    )
    assert data["repair_issues"] == [f"{rig.entry.entry_id}_{HUMIDITY}"]
