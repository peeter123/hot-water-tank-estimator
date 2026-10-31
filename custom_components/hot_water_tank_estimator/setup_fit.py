"""The setup fit: replay recorded history through the model and fit the parameters.

Pure Python: standard library only, no Home Assistant imports and no I/O. The history comes in
as a neutral structure, `History`, that the fixtures of `tests/fixtures/`, the exports in
`private/history/` and Home Assistant's recorder can all be turned into. The same replay serves
the setup fit of a config entry, the `recalibrate` action and `scripts/backtest.py`.

`replay` feeds the states in time order to the `on_*` methods of a `TankModel`, with a tick
every 5 minutes as the runtime does. `setup_fit` replays with a `Calibrator` that learns as it
goes (the live learning rules: at least 5 intervals, one step at most per update). `evaluate`
replays with fixed options and reports the charge errors, so the fitted options can be compared
with the defaults.

The first charge of a replay is a sensor start, never a closure: the model starts at the tank
sensor's reading, which ignores the draws since the last real charge.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import accumulate
from typing import Any

from .calibration import (
    PARAMETER_BOUNDS,
    SOURCE_SETUP_FIT,
    USABLE_FRACTION,
    Calibrator,
    Closure,
)
from .const import DEFAULT_SESSION_GAP
from .model import EventKind, ModelEvent, ModelOptions, Outputs, Sources, TankModel

TICK = timedelta(minutes=5)
DEFAULT_WATER_UNIT = "m3"
DEFAULT_START_TEMPERATURE = 50.0  # C, when the tank sensor has no reading at the start

# The roles of the history series, as in the fixtures.
TANK_TEMPERATURE = "tank_temperature"
WATER_METER = "water_meter"
DHW_ENERGY = "dhw_energy"
DHW_POWER = "dhw_power"
DHW_HEATING = "dhw_heating"
FLOW_TEMPERATURE = "flow_temperature"
RETURN_TEMPERATURE = "return_temperature"
BATHROOM_HUMIDITY = "bathroom_humidity"
COLD_WATER_TEMPERATURE = "cold_water_temperature"


@dataclass(frozen=True)
class Series:
    """The recorded states of one source.

    Attributes:
        role: What the source is, one of the role constants above.
        entity_id: The source's identifier (it tells several humidity sensors apart).
        unit: The unit of measurement, None when unknown.
        states: `(time, state text)` rows in time order. The first row is the state in force at
            the start of the history. `unavailable` and any other non-numeric text is allowed.
    """

    role: str
    entity_id: str
    unit: str | None
    states: Sequence[tuple[datetime, str]]


@dataclass(frozen=True)
class History:
    """Recorded history of the sources of one tank.

    Attributes:
        start: The first moment of the history.
        end: The last moment of the history.
        series: The recorded sources.
    """

    start: datetime
    end: datetime
    series: Sequence[Series]

    def since(self, start: datetime) -> History:
        """Return the history from `start` on, with the state in force at `start` first."""
        if start <= self.start:
            return self
        cut: list[Series] = []
        for series in self.series:
            rows = list(series.states)
            index = sum(1 for time, _ in rows if time <= start)
            held = [(start, rows[index - 1][1])] if index else []
            cut.append(
                Series(series.role, series.entity_id, series.unit, held + rows[index:])
            )
        return History(start, self.end, cut)

    def last_days(self, days: float) -> History:
        """Return the last `days` days of the history."""
        return self.since(self.end - timedelta(days=days))


def history_from_fixture(data: Mapping[str, Any]) -> History:
    """Return the history of a fixture (the format of `scripts/anonymise.py`)."""
    series = [
        Series(
            role=entity["role"],
            entity_id=entity_id,
            unit=entity.get("unit_of_measurement"),
            states=[(datetime.fromisoformat(t), str(s)) for t, s in entity["states"]],
        )
        for entity_id, entity in data["entities"].items()
    ]
    return History(
        datetime.fromisoformat(data["window"]["start"]),
        datetime.fromisoformat(data["window"]["end"]),
        series,
    )


def sources_for(history: History) -> Sources:
    """Return which sources the history has: the heat input, flow and return, humidity, cold."""
    roles = {series.role for series in history.series}
    return Sources(
        energy_counter=DHW_ENERGY in roles,
        power=DHW_POWER in roles,
        heating_binary=DHW_HEATING in roles,
        flow_return=FLOW_TEMPERATURE in roles and RETURN_TEMPERATURE in roles,
        cold_sensor=COLD_WATER_TEMPERATURE in roles,
        humidity_sensors=tuple(
            series.entity_id
            for series in history.series
            if series.role == BATHROOM_HUMIDITY
        ),
    )


@dataclass(frozen=True)
class Snap:
    """The model after one input or tick."""

    time: datetime
    t_avg: float
    t_ch: float
    t_cold: float
    outputs: Outputs
    tank_litres: float
    shower_litres: float
    detected: bool
    heating: bool


@dataclass
class ReplayResult:
    """The result of a replay.

    Attributes:
        model: The model at the end of the history.
        events: Every model event, oldest first.
        snaps: The model after every input and tick (empty unless recorded).
        calibrator: The calibrator that watched the replay, if any.
    """

    model: TankModel
    events: list[ModelEvent]
    snaps: list[Snap]
    calibrator: Calibrator | None = None


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
        outputs=model.outputs,
        tank_litres=model.tank_litres_exact,
        shower_litres=model.shower_litres_exact,
        detected=model.shower_detected,
        heating=model.heating,
    )


def replay(
    history: History,
    options: ModelOptions,
    *,
    sources: Sources | None = None,
    calibrator: Calibrator | None = None,
    tick: timedelta = TICK,
    record: bool = False,
) -> ReplayResult:
    """Replay a history through a model, with a tick every `tick`.

    The model starts at the tank sensor's first reading, charged. With a calibrator, every
    input is observed and a change of the learned options is applied to the model.

    Args:
        history: The recorded states.
        options: The options to start with (a calibrator's own options replace them).
        sources: Which sources are configured, by default those the history has.
        calibrator: A calibrator to learn with, or None for fixed options.
        tick: The tick interval.
        record: Whether to record a snapshot of the outputs after every step.

    Returns:
        The model, its events and the snapshots.
    """
    sources = sources or sources_for(history)
    if calibrator is not None:
        options = calibrator.options
    rows = sorted(
        (
            (time, index, series, state)
            for index, series in enumerate(history.series)
            for time, state in series.states
        ),
        key=lambda row: (row[0], row[1]),
    )
    # The first numeric reading: a tank sensor that is unavailable at the start is skipped.
    first_tank = next(
        (
            value
            for _, _, series, state in rows
            if series.role == TANK_TEMPERATURE and (value := _number(state)) is not None
        ),
        None,
    )
    model = TankModel(
        options,
        sources,
        history.start,
        first_tank if first_tank is not None else DEFAULT_START_TEMPERATURE,
    )
    events: list[ModelEvent] = []
    snaps: list[Snap] = []
    flow: float | None = None
    ret: float | None = None

    def step(now: datetime, new: list[ModelEvent]) -> None:
        events.extend(new)
        if calibrator is not None and calibrator.observe(model, new, now):
            model.set_options(calibrator.options)
        if record:
            snaps.append(_snap(model, now))

    next_tick = history.start + tick

    def tick_until(limit: datetime) -> None:
        nonlocal next_tick
        while next_tick <= limit:
            step(next_tick, model.tick(next_tick))
            next_tick += tick

    for time, _, series, state in rows:
        tick_until(time)
        value = _number(state)
        match series.role:
            case "tank_temperature":
                new = model.on_tank_sensor(time, value)
            case "water_meter":
                new = model.on_water_meter(
                    time, value, series.unit or DEFAULT_WATER_UNIT
                )
            case "dhw_energy":
                new = model.on_energy(time, value)
            case "dhw_power":
                new = model.on_power(time, value)
            case "dhw_heating":
                new = model.on_heating(time, {"on": True, "off": False}.get(state))
            case "flow_temperature" | "return_temperature":
                if series.role == FLOW_TEMPERATURE:
                    flow = value
                else:
                    ret = value
                new = model.on_flow_return(time, flow, ret)
            case "bathroom_humidity":
                new = model.on_humidity(time, series.entity_id, value)
            case "cold_water_temperature":
                new = model.on_cold_water_sensor(time, value)
            case _:
                raise ValueError(f"Unknown role {series.role}")
        step(time, new)
    tick_until(history.end)
    if calibrator is not None and calibrator.flush():
        model.set_options(calibrator.options)
    return ReplayResult(model, events, snaps, calibrator)


@dataclass(frozen=True)
class SetupFit:
    """The result of the setup fit.

    Attributes:
        options: The options with the fitted values applied (locked ones keep the option).
        calibrator: The calibrator after the replay: values, sources, closures and estimates.
        locks: The locked parameters.
    """

    options: ModelOptions
    calibrator: Calibrator
    locks: frozenset[str] = frozenset()

    @property
    def closures(self) -> list[Closure]:
        """Return every closure of the replay, with its status and charge error."""
        return list(self.calibrator.closures)

    @property
    def intervals(self) -> list[Closure]:
        """Return the valid closures."""
        return self.calibrator.intervals

    @property
    def parameters(self) -> dict[str, tuple[float, str]]:
        """Return each learnable parameter with its value and source."""
        return {
            name: (self.calibrator.value_of(name), self.calibrator.source_of(name))
            for name in PARAMETER_BOUNDS
        }


def setup_fit(
    history: History,
    options: ModelOptions,
    *,
    locks: Iterable[str] = (),
    sources: Sources | None = None,
    tick: timedelta = TICK,
    previous: Calibrator | None = None,
) -> SetupFit:
    """Fit the parameters to a history by replaying it with live learning.

    Closures of the replay train the share, the start-up energy and the loss coefficient from
    the fifth interval on, quiet windows the loss coefficient before that, and first sensor
    drops the thermocline width. Locked parameters keep their option value, and parameters
    with too little data keep theirs too.

    Args:
        history: The recorded states, up to the configured number of days.
        options: The configured options.
        locks: The locked parameters.
        sources: Which sources are configured, by default those the history has.
        tick: The tick interval.
        previous: The calibrator this fit replaces (a recalibrate). The usable fraction it
            learned from the button stays with its source, because no replay can learn it.

    Returns:
        The fitted options and the calibration state. The calibrator is ready for live
        learning: its further changes are labelled `learned`, while the parameters the fit
        changed keep the source `setup_fit`.
    """
    sources = sources or sources_for(history)
    calibrator = Calibrator(
        options,
        locks=frozenset(locks),
        measures_heat=sources.energy_counter or sources.power,
        label=SOURCE_SETUP_FIT,
    )
    if previous is not None and USABLE_FRACTION in previous.values:
        if USABLE_FRACTION not in calibrator.locks:
            calibrator.values[USABLE_FRACTION] = previous.values[USABLE_FRACTION]
            calibrator.sources[USABLE_FRACTION] = previous.sources[USABLE_FRACTION]
    replay(history, options, sources=sources, calibrator=calibrator, tick=tick)
    calibrator.go_live()
    return SetupFit(calibrator.options, calibrator, calibrator.locks)


@dataclass(frozen=True)
class Shower:
    """One shower session and the outputs through it.

    Attributes:
        start: Time of the session's first litre.
        end: Time of its last litre.
        litres: All litres of the session.
        mixed_litres: The litres that counted as a mixed draw.
        points: `(litres drawn so far, snapshot)` at the start, each quarter and the end.
    """

    start: datetime
    end: datetime
    litres: float
    mixed_litres: float
    points: list[tuple[float, Snap]] = field(default_factory=list)


@dataclass(frozen=True)
class Evaluation:
    """A replay with fixed options: the charge errors and the showers.

    Attributes:
        options: The options used.
        closures: Every closure with its status, reason and charge error.
        replay: The replay (with snapshots).
    """

    options: ModelOptions
    closures: list[Closure]
    replay: ReplayResult

    @property
    def intervals(self) -> list[Closure]:
        """Return the valid closures."""
        return [c for c in self.closures if c.status == "closure"]

    @property
    def mean_abs_error(self) -> float | None:
        """Return the mean absolute charge error over the valid closures in K."""
        errors = [abs(c.error) for c in self.intervals if c.error is not None]
        return sum(errors) / len(errors) if errors else None

    def showers(
        self, minimum_mixed: float = 50.0, gap: float = DEFAULT_SESSION_GAP
    ) -> list[Shower]:
        """Return the sessions with at least `minimum_mixed` litres of mixed draw.

        A gap of more than `gap` seconds between draws starts a new session.
        """
        draws = [
            e
            for e in self.replay.events
            if e.kind == EventKind.DRAW and "litres" in e.change
        ]
        sessions: list[list[ModelEvent]] = []
        for event in draws:
            if sessions and (event.time - sessions[-1][-1].time).total_seconds() <= gap:
                sessions[-1].append(event)
            else:
                sessions.append([event])
        result = []
        for session in sessions:
            mixed = sum(e.change["litres"] for e in session if e.change["mixed"])
            if mixed < minimum_mixed:
                continue
            total = sum(e.change["litres"] for e in session)
            result.append(
                Shower(
                    session[0].time,
                    session[-1].time,
                    total,
                    mixed,
                    self._points(session, total),
                )
            )
        return result

    def _points(
        self, session: list[ModelEvent], total: float
    ) -> list[tuple[float, Snap]]:
        """Return the snapshots at the start, each quarter and the end of a session."""
        times = [snap.time for snap in self.replay.snaps]
        cumulative = list(accumulate(e.change["litres"] for e in session))
        points: list[tuple[float, Snap]] = []
        # Just before the first litre.
        index = bisect_left(times, session[0].time)
        if index:
            points.append((0.0, self.replay.snaps[index - 1]))
        for quarter in (0.25, 0.5, 0.75, 1.0):
            reached = next(
                i
                for i, litres in enumerate(cumulative)
                if litres >= quarter * total - 1e-9
            )
            index = bisect_right(times, session[reached].time)
            if index:
                points.append((cumulative[reached], self.replay.snaps[index - 1]))
        return points


def evaluate(
    history: History,
    options: ModelOptions,
    *,
    sources: Sources | None = None,
    tick: timedelta = TICK,
) -> Evaluation:
    """Replay a history with fixed options and report the charge errors and showers."""
    sources = sources or sources_for(history)
    calibrator = Calibrator(
        options,
        measures_heat=sources.energy_counter or sources.power,
        learn=False,
    )
    result = replay(
        history,
        options,
        sources=sources,
        calibrator=calibrator,
        tick=tick,
        record=True,
    )
    return Evaluation(options, list(calibrator.closures), result)


__all__ = [
    "Evaluation",
    "History",
    "ReplayResult",
    "Series",
    "SetupFit",
    "Shower",
    "Snap",
    "evaluate",
    "history_from_fixture",
    "replay",
    "setup_fit",
    "sources_for",
]
