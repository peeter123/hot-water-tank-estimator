"""Replay of recorded history through the tank model.

Each fixture in `tests/fixtures/` is a window of real history with made-up entity IDs (see
`scripts/anonymise.py` for the format). The replay feeds the states in time order to the `on_*`
methods of the model with the default options, and calls `tick` every 5 minutes, as the runtime
does. The tank volume and sensor height come from the fixture's own metadata.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from itertools import pairwise
import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.hot_water_tank_estimator.const import (
    DEFAULT_RECLASSIFY_WINDOW,
    DEFAULT_SESSION_GAP,
    DEFAULT_THERMOCLINE_WIDTH,
)
from custom_components.hot_water_tank_estimator.model import (
    EventKind,
    ModelEvent,
    ModelOptions,
    Sources,
    TankModel,
)

FIXTURES = Path(__file__).parent / "fixtures"
TICK = timedelta(minutes=5)
SESSION_GAP = timedelta(seconds=DEFAULT_SESSION_GAP)
HUMIDITY_ID = "sensor.bathroom_humidity"
STARTUP_ENERGY = 1.8  # kWh per run, the fitted value for the tank of the recordings


@dataclass(frozen=True)
class Snap:
    """The model after one input or tick."""

    time: datetime
    t_avg: float
    t_ch: float
    t_cold: float
    tank_litres: float
    shower_litres: float
    detected: bool
    heating: bool


@dataclass
class Replay:
    """The result of a replay: the final model, a snapshot per step and every event."""

    model: TankModel
    snaps: list[Snap]
    events: list[ModelEvent]
    meta: dict[str, Any]

    def draws(self) -> list[ModelEvent]:
        """Return the draw events that drew water (not reclassifications)."""
        return [
            e for e in self.events if e.kind == EventKind.DRAW and "litres" in e.change
        ]

    def reclassifications(self) -> list[ModelEvent]:
        """Return the events that moved litres from other to mixed draws."""
        return [
            e
            for e in self.events
            if e.kind == EventKind.DRAW and "reclassified_litres" in e.change
        ]

    def sessions(self) -> list[list[ModelEvent]]:
        """Group the draws into sessions: a gap of more than the session gap starts a new one."""
        sessions: list[list[ModelEvent]] = []
        for event in self.draws():
            if sessions and event.time - sessions[-1][-1].time <= SESSION_GAP:
                sessions[-1].append(event)
            else:
                sessions.append([event])
        return sessions

    def mixed_sessions(self, minimum: float) -> list[list[ModelEvent]]:
        """Return the sessions with at least `minimum` litres of mixed draw."""
        return [
            s
            for s in self.sessions()
            if sum(e.change["litres"] for e in s if e.change["mixed"]) >= minimum
        ]

    def snaps_between(self, start: datetime, end: datetime) -> list[Snap]:
        """Return the snapshots from `start` to `end`, both included."""
        return [s for s in self.snaps if start <= s.time <= end]

    def charges(self) -> list[ModelEvent]:
        """Return the charge events of heating runs."""
        return [
            e
            for e in self.events
            if e.kind == EventKind.CHARGE and "run_end" in e.change
        ]


def load_fixture(name: str) -> dict[str, Any]:
    """Load a fixture file."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _number(state: str) -> float | None:
    """Return a state as a number, None when unavailable or not numeric."""
    try:
        return float(state)
    except ValueError:
        return None


def _snap(model: TankModel, now: datetime) -> Snap:
    """Return the model's figures now."""
    return Snap(
        time=now,
        t_avg=model.t_avg,
        t_ch=model.t_ch,
        t_cold=model.t_cold,
        tank_litres=model.tank_litres_exact,
        shower_litres=model.shower_litres_exact,
        detected=model.shower_detected,
        heating=model.heating,
    )


@cache
def replay(name: str, startup_energy: float = 0.0) -> Replay:
    """Replay a fixture with the default options and a tick every 5 minutes.

    Args:
        name: The fixture name.
        startup_energy: The start-up energy per run in kWh (0 is the default).

    Returns:
        The replay result.
    """
    fixture = load_fixture(name)
    options = ModelOptions(
        volume=fixture["tank"]["volume"],
        sensor_height=fixture["tank"]["sensor_height"],
        startup_energy=startup_energy,
    )
    start = datetime.fromisoformat(fixture["window"]["start"])
    end = datetime.fromisoformat(fixture["window"]["end"])

    rows: list[tuple[datetime, str, str]] = []
    units: dict[str, str | None] = {}
    for entity in fixture["entities"].values():
        units[entity["role"]] = entity.get("unit_of_measurement")
        rows.extend(
            (datetime.fromisoformat(time), entity["role"], state)
            for time, state in entity["states"]
        )
    rows.sort(key=lambda row: row[0])  # stable: equal times keep the fixture's order

    tank_rows = [state for _, role, state in rows if role == "tank_temperature"]
    first_tank = _number(tank_rows[0]) if tank_rows else None
    model = TankModel(
        options,
        Sources(
            energy_counter=True,
            heating_binary=True,
            flow_return=True,
            humidity_sensors=(HUMIDITY_ID,),
        ),
        start,
        first_tank if first_tank is not None else 50.0,
    )

    events: list[ModelEvent] = []
    snaps: list[Snap] = []
    flow: float | None = None
    ret: float | None = None
    next_tick = start + TICK

    def tick_until(limit: datetime) -> None:
        nonlocal next_tick
        while next_tick <= limit:
            events.extend(model.tick(next_tick))
            snaps.append(_snap(model, next_tick))
            next_tick += TICK

    for time, role, state in rows:
        tick_until(time)
        value = _number(state)
        match role:
            case "tank_temperature":
                events.extend(model.on_tank_sensor(time, value))
            case "water_meter":
                events.extend(model.on_water_meter(time, value, units[role] or ""))
            case "dhw_energy":
                events.extend(model.on_energy(time, value))
            case "dhw_heating":
                active = {"on": True, "off": False}.get(state)
                events.extend(model.on_heating(time, active))
            case "flow_temperature" | "return_temperature":
                if role == "flow_temperature":
                    flow = value
                else:
                    ret = value
                events.extend(model.on_flow_return(time, flow, ret))
            case "bathroom_humidity":
                events.extend(model.on_humidity(time, HUMIDITY_ID, value))
            case _:
                raise AssertionError(f"unknown role {role}")
        snaps.append(_snap(model, time))
    tick_until(end)
    return Replay(model, snaps, events, fixture)


def test_week_loads() -> None:
    """The week fixture loads and has the roles the model uses (group 4 replays it)."""
    fixture = load_fixture("week")
    roles = {entity["role"] for entity in fixture["entities"].values()}
    assert roles == {
        "tank_temperature",
        "water_meter",
        "dhw_energy",
        "dhw_heating",
        "flow_temperature",
        "return_temperature",
        "bathroom_humidity",
    }
    assert fixture["tank"]["volume"] > 0


def _cumulative(session: list[ModelEvent], now: datetime) -> float:
    """Return the litres a session had drawn by `now`."""
    return sum(e.change["litres"] for e in session if e.time <= now)


def _last_snap(result: Replay, now: datetime) -> Snap:
    """Return the last snapshot at or before `now`."""
    return [s for s in result.snaps if s.time <= now][-1]


def test_long_shower() -> None:
    """A 240 L shower: shower water lasts past 200 L, the tank is nearly empty, the charge fits."""
    result = replay("long_shower")
    (session,) = result.mixed_sessions(100)
    # The window holds an earlier charge (the sensor-start charge); the recovery run follows the shower.
    first_charge = next(c for c in result.charges() if c.time > session[-1].time)

    # Shower water stays above 0 until at least 200 L into the session.
    snaps = result.snaps_between(session[0].time, first_charge.time)
    zero = next((s for s in snaps if round(s.shower_litres) == 0), None)
    litres_at_zero = float("inf") if zero is None else _cumulative(session, zero.time)
    assert litres_at_zero >= 200

    # Tank water is 0-60 L at the end of the session.
    end = _last_snap(result, session[-1].time)
    assert 0 <= round(end.tank_litres) <= 60

    # The charge at the end of the recovery run is within 3 K of the model before it.
    with_startup = replay("long_shower", STARTUP_ENERGY)
    (charge,) = [c for c in with_startup.charges() if c.time > session[-1].time]
    assert charge.change["source"] == "flow_return"
    assert abs(charge.t_avg_before - charge.change["charge_temperature"]) <= 3.0


def test_shower_unseen() -> None:
    """A 141 L shower the tank sensor does not see: the lower bound holds T_avg up."""
    result = replay("shower_unseen")
    (session,) = [
        s
        for s in result.mixed_sessions(100)
        if abs(sum(e.change["litres"] for e in s) - 141) < 0.5
    ]
    h = result.meta["tank"]["sensor_height"]
    f_lo = h - DEFAULT_THERMOCLINE_WIDTH / 2
    snaps = result.snaps_between(session[0].time, session[-1].time)
    assert snaps
    for snap in snaps:
        floor = snap.t_ch - f_lo * (snap.t_ch - snap.t_cold)
        assert snap.t_avg >= floor - 1e-9
        assert snap.shower_litres > 150
    bounds = [
        e
        for e in result.events
        if e.kind == EventKind.SENSOR_BOUND
        and "lower_bound" in e.change["rules"]
        and session[0].time <= e.time <= session[-1].time
    ]
    assert bounds


def test_back_to_back() -> None:
    """Two showers in a row: no litre of either stays an other draw, and a cap acts in the second."""
    result = replay("back_to_back")
    first, second = result.mixed_sessions(50)[:2]
    reclassified = result.reclassifications()
    for session in (first, second):
        start, end = session[0].time, session[-1].time
        mixed = sum(e.change["litres"] for e in session if e.change["mixed"])
        moved = sum(
            e.change["reclassified_litres"]
            for e in reclassified
            if start <= e.time <= end
        )
        total = sum(e.change["litres"] for e in session)
        assert mixed + moved == total
    assert any(first[0].time <= e.time <= first[-1].time for e in reclassified)

    caps = [
        e
        for e in result.events
        if e.kind == EventKind.SENSOR_BOUND
        and {"cold_cap", "thermocline_cap"} & set(e.change["rules"])
        and second[0].time <= e.time <= second[-1].time
    ]
    assert caps


def test_late_detection() -> None:
    """Detection 6.3 minutes into a session reclassifies every litre drawn before it."""
    result = replay("late_detection")
    window = timedelta(minutes=DEFAULT_RECLASSIFY_WINDOW)
    (session,) = [
        s
        for s in result.sessions()
        if abs(sum(e.change["litres"] for e in s) - 52) < 0.5
    ]
    start, end = session[0].time, session[-1].time
    (detection,) = [e for e in result.reclassifications() if start <= e.time <= end]
    delay = detection.time - start
    assert timedelta(minutes=6) <= delay <= timedelta(minutes=6.6)
    assert delay < window
    before = [e for e in session if e.time <= detection.time and not e.change["mixed"]]
    assert before
    assert detection.change["reclassified_litres"] == sum(
        e.change["litres"] for e in before
    )
    # Every litre of the session ends as a mixed draw.
    mixed = sum(e.change["litres"] for e in session if e.change["mixed"])
    assert mixed + detection.change["reclassified_litres"] == sum(
        e.change["litres"] for e in session
    )


def test_quiet_days() -> None:
    """No output falls more than 10 % in a night without draws."""
    result = replay("quiet_days")
    draw_times = [e.time for e in result.draws()]
    window = result.meta["window"]
    edges = [
        datetime.fromisoformat(window["start"]),
        *draw_times,
        datetime.fromisoformat(window["end"]),
    ]
    nights = [(a, b) for a, b in pairwise(edges) if b - a >= timedelta(hours=6)]
    assert len(nights) >= 2
    for start, end in nights:
        snaps = result.snaps_between(start, end)
        assert not any(s.heating for s in snaps)
        first, last = snaps[0], snaps[-1]
        # Percent charged and shower minutes are proportional to these two.
        assert last.tank_litres >= 0.9 * first.tank_litres
        assert last.shower_litres >= 0.9 * first.shower_litres


@pytest.mark.parametrize(
    "name",
    [
        "long_shower",
        "shower_unseen",
        "back_to_back",
        "late_detection",
        "quiet_days",
        "week",
    ],
)
def test_fixture_size(name: str) -> None:
    """Each fixture stays under 500 kB."""
    assert (FIXTURES / f"{name}.json").stat().st_size < 500_000
