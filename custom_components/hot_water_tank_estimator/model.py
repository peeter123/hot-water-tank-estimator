"""Two-layer tank model: how much hot water is left in a domestic hot water tank.

Pure Python: standard library only, no Home Assistant imports and no I/O. The formulas and
their symbols are those of `docs/model.md`:

- `t_avg` is the tank average temperature in C, `t_ch` the charged temperature of the hot
  layer in C, `t_cold` the cold water temperature in C and `t_mix` the shower mix temperature.
- `f = (t_ch - t_avg) / (t_ch - t_cold)` is the cold fraction (0-1).
- `h` is the sensor height and `w` the thermocline width, both fractions of the tank.
- `u` is the usable fraction of the tank.
- `V` is the tank volume in litres. Energy is `V * 1.163 * t_avg` Wh above 0 C.

Every input method takes a timezone-aware `datetime` and a number (None when the source is
unavailable) and returns the events it caused. The same calls serve the Home Assistant runtime,
the replay tests and the backtest.
"""

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
import math
from typing import Any

from .classification import ClassifierOptions, DrawClassifier
from .const import (
    CHARGE_WINDOW_SECONDS,
    COUNTER_LAG_SECONDS,
    DEFAULT_AMBIENT_FALLBACK,
    DEFAULT_AMBIENT_TEMPERATURE,
    DEFAULT_COLD_AMPLITUDE,
    DEFAULT_COLD_COLDEST_DAY,
    DEFAULT_COLD_MEAN,
    DEFAULT_HUMIDITY_RISE,
    DEFAULT_HUMIDITY_WINDOW,
    DEFAULT_LONG_DRAW_MINUTES,
    DEFAULT_LOSS_COEFFICIENT,
    DEFAULT_MAX_DRAW,
    DEFAULT_MAX_TEMPERATURE,
    DEFAULT_MIX_TEMPERATURE,
    DEFAULT_OTHER_HOT_SHARE,
    DEFAULT_POWER_THRESHOLD,
    DEFAULT_RECLASSIFY_WINDOW,
    DEFAULT_SENSOR_HEIGHT,
    DEFAULT_SENSOR_MARGIN,
    DEFAULT_SENSOR_TOLERANCE,
    DEFAULT_SESSION_GAP,
    DEFAULT_SHOWER_FLOW,
    DEFAULT_STARTUP_ENERGY,
    DEFAULT_THERMOCLINE_WIDTH,
    DEFAULT_USABLE_FRACTION,
    DETECTOR_HOLD_SECONDS,
    HEATING_TIMEOUT_SECONDS,
    WATER_HEAT_CAPACITY_WH,
)

STATE_VERSION = 1

# Flow and return readings are kept this long: the counter timeout (10 min) is found late, and
# the charge window (2 min) lies before the last counter increase, so keep 10 + 2 min plus margin.
_RING_RETENTION_SECONDS = 1200.0


class EventKind(StrEnum):
    """The kinds of model event."""

    DRAW = "draw"
    HEAT = "heat"
    CHARGE = "charge"
    LOSS = "loss"
    SENSOR_BOUND = "sensor_bound"
    CALIBRATION = "calibration"
    HOT_WATER_RAN_OUT = "hot_water_ran_out"


@dataclass(frozen=True)
class ModelEvent:
    """One change of the model, for diagnostics and calibration.

    Attributes:
        time: When it happened.
        kind: What kind of change it was.
        change: The input change, for example litres drawn or kWh of heat. A charge event
            carries the run and interval figures calibration needs.
        t_avg_before: Tank average before the change, in C.
        t_avg_after: Tank average after the change, in C.
        t_ch_before: Charged temperature before the change, in C.
        t_ch_after: Charged temperature after the change, in C.
    """

    time: datetime
    kind: EventKind
    change: dict[str, Any]
    t_avg_before: float
    t_avg_after: float
    t_ch_before: float
    t_ch_after: float

    def as_dict(self) -> dict[str, Any]:
        """Return the event as a JSON-compatible dict."""
        return {
            "time": self.time.isoformat(),
            "kind": str(self.kind),
            "change": self.change,
            "t_avg_before": self.t_avg_before,
            "t_avg_after": self.t_avg_after,
            "t_ch_before": self.t_ch_before,
            "t_ch_after": self.t_ch_after,
        }


@dataclass(frozen=True)
class DrawEnd:
    """The state of the tank at the end of a draw session.

    Attributes:
        time: When the session ended (the time of its last increase).
        cold_fraction: The cold fraction f at that moment.
        t_ch: The charged temperature at that moment, in C.
        t_avg: The tank average at that moment, in C.
        t_cold: The cold water temperature at that moment, in C.
        tank_sensor: The tank sensor reading at that moment in C, None when unavailable.
        usable_fraction: The usable fraction in use at that moment.
    """

    time: datetime
    cold_fraction: float
    t_ch: float
    t_avg: float
    t_cold: float
    tank_sensor: float | None
    usable_fraction: float

    def as_dict(self) -> dict[str, Any]:
        """Return the record as a JSON-compatible dict."""
        return {
            "time": self.time.isoformat(),
            "cold_fraction": self.cold_fraction,
            "t_ch": self.t_ch,
            "t_avg": self.t_avg,
            "t_cold": self.t_cold,
            "tank_sensor": self.tank_sensor,
            "usable_fraction": self.usable_fraction,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DrawEnd:
        """Return the record saved by `as_dict`."""
        sensor = data["tank_sensor"]
        return cls(
            time=datetime.fromisoformat(data["time"]),
            cold_fraction=float(data["cold_fraction"]),
            t_ch=float(data["t_ch"]),
            t_avg=float(data["t_avg"]),
            t_cold=float(data["t_cold"]),
            tank_sensor=None if sensor is None else float(sensor),
            usable_fraction=float(data["usable_fraction"]),
        )


@dataclass(frozen=True, kw_only=True)
class ModelOptions:
    """The tuning values of the tank model. The defaults are in `const.py`."""

    volume: float  # V, litres
    sensor_height: float = DEFAULT_SENSOR_HEIGHT  # h, fraction of the tank
    thermocline_width: float = DEFAULT_THERMOCLINE_WIDTH  # w, fraction of the tank
    usable_fraction: float = DEFAULT_USABLE_FRACTION  # u
    mix_temperature: float = DEFAULT_MIX_TEMPERATURE  # t_mix, C
    max_temperature: float = DEFAULT_MAX_TEMPERATURE  # t_max, C
    sensor_tolerance: float = DEFAULT_SENSOR_TOLERANCE  # delta, K
    sensor_margin: float = DEFAULT_SENSOR_MARGIN  # m, K
    ambient_temperature: float = DEFAULT_AMBIENT_TEMPERATURE  # t_ambient, C
    ambient_fallback: float = DEFAULT_AMBIENT_FALLBACK  # hours
    cold_mean: float = DEFAULT_COLD_MEAN  # C
    cold_amplitude: float = DEFAULT_COLD_AMPLITUDE  # K
    cold_coldest_day: int = DEFAULT_COLD_COLDEST_DAY  # day of the year
    loss_coefficient: float = DEFAULT_LOSS_COEFFICIENT  # k, per hour
    other_hot_share: float = (
        DEFAULT_OTHER_HOT_SHARE  # share of other-draw litres that is hot
    )
    startup_energy: float = DEFAULT_STARTUP_ENERGY  # S, kWh per run
    shower_flow: float = DEFAULT_SHOWER_FLOW  # L/min
    humidity_rise: float = DEFAULT_HUMIDITY_RISE  # percentage points
    humidity_window: float = DEFAULT_HUMIDITY_WINDOW  # minutes
    long_draw_minutes: float = DEFAULT_LONG_DRAW_MINUTES  # 0 is off
    reclassify_window: float = DEFAULT_RECLASSIFY_WINDOW  # minutes
    session_gap: float = DEFAULT_SESSION_GAP  # seconds
    max_draw: float = DEFAULT_MAX_DRAW  # litres per reading
    power_threshold: float = DEFAULT_POWER_THRESHOLD  # W

    def classifier_options(self) -> ClassifierOptions:
        """Return the part of the options the draw classification uses."""
        return ClassifierOptions(
            humidity_rise=self.humidity_rise,
            humidity_window=self.humidity_window,
            long_draw_minutes=self.long_draw_minutes,
            reclassify_window=self.reclassify_window,
            session_gap=self.session_gap,
            max_draw=self.max_draw,
        )


@dataclass(frozen=True)
class Sources:
    """Which heat sources and optional sensors are configured.

    The rules differ per combination: counter, power or binary-only heat, flow and return or
    not, a cold water sensor or not, an ambient sensor or not. The tank sensor and the water
    meter are always present.
    """

    energy_counter: bool = False
    power: bool = False
    heating_binary: bool = False
    flow_return: bool = False
    cold_sensor: bool = False
    ambient_sensor: bool = False
    humidity_sensors: tuple[str, ...] = ()


@dataclass
class IntervalSums:
    """Energy balance sums since the last charge, without the sensor bounds.

    Calibration fits `T_ch_prev - T_true_start = loss * k + other * share + mixed`.

    Attributes:
        hours: Hours since the last charge.
        loss: Sum of `(t_avg - t_ambient) * dt` in K*h.
        other: Sum of `dV * (t_ch - t_cold) / V` over other draws in K, for a share of 1.
        mixed: Sum of the mixed-draw drops in K.
    """

    hours: float = 0.0
    loss: float = 0.0
    other: float = 0.0
    mixed: float = 0.0

    def as_dict(self) -> dict[str, float]:
        """Return the sums as a JSON-compatible dict."""
        return {
            "hours": self.hours,
            "loss": self.loss,
            "other": self.other,
            "mixed": self.mixed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> IntervalSums:
        """Create the sums from `as_dict` output."""
        return cls(
            hours=float(data["hours"]),
            loss=float(data["loss"]),
            other=float(data["other"]),
            mixed=float(data["mixed"]),
        )


@dataclass(frozen=True)
class Outputs:
    """The four outputs of the model.

    Attributes:
        tank_litres: Litres of tank water at the charged temperature that can still be drawn.
        shower_litres: Litres of mixed water at the mix temperature the tank water makes.
        percent_charged: Percent of the usable tank compared with the last charge.
        shower_minutes: Minutes of shower left.
    """

    tank_litres: int
    shower_litres: int
    percent_charged: int
    shower_minutes: int


def _finite(value: Any) -> bool:
    """Return whether a value is a real number (not None, bool, NaN or infinite)."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _clamp01(value: float) -> float:
    """Limit a value to 0-1."""
    return min(1.0, max(0.0, value))


def _round_half_up(value: float) -> int:
    """Round a non-negative value to a whole number, halves up."""
    return int(value + 0.5)


def _iso(value: datetime | None) -> str | None:
    """Return an ISO string for a datetime, or None."""
    return None if value is None else value.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    """Return the datetime of an ISO string, or None."""
    return None if value is None else datetime.fromisoformat(value)


class TankModel:
    """The two-layer tank model and its draw classification."""

    def __init__(
        self,
        options: ModelOptions,
        sources: Sources,
        now: datetime,
        t_avg: float,
        t_ch: float | None = None,
        *,
        max_events: int = 500,
        cold_sensor: float | None = None,
        ambient_sensor: float | None = None,
    ) -> None:
        """Create a model that is charged (or, with `t_ch` above `t_avg`, part drawn).

        Args:
            options: The tuning values.
            sources: Which sources are configured.
            now: The start time.
            t_avg: The tank average in C.
            t_ch: The charged temperature in C, `t_avg` when omitted.
            max_events: Size of the event log.
            cold_sensor: The cold water sensor reading in C, if one is available now.
            ambient_sensor: The ambient sensor reading in C, if one is available now.
        """
        self.options = options
        self.sources = sources
        self.t_avg = t_avg
        self.t_ch = t_avg if t_ch is None else t_ch
        # The same balance without sensor bounds, for the calibration sums.
        self._bal_avg = self.t_avg
        self._bal_ch = self.t_ch
        self._now = now
        self._classifier = DrawClassifier(options.classifier_options())
        # The last draw session that ended, and the state after the latest draw increase,
        # which becomes that record when the classifier reports the session's end.
        self._draw_end: DrawEnd | None = None
        self._last_draw: DrawEnd | None = None
        # When T_avg was last replaced: a charge or a manual set_state (the button's reset too).
        self._last_reset: datetime | None = None
        self._events: deque[ModelEvent] = deque(maxlen=max_events)

        self._tank_sensor: float | None = None
        self._cold_sensor: float | None = cold_sensor
        self._ambient_sensor: float | None = ambient_sensor
        # Set on restore: when the restored sensor reading was last known good.
        self._ambient_restored: datetime | None = None
        # The last ambient reading and the time it was last known good (when the sensor went
        # unavailable): it stays in use for `ambient_fallback` hours after that.
        self._ambient_last: tuple[float, datetime] | None = (
            None if ambient_sensor is None else (ambient_sensor, now)
        )
        self._binary: bool | None = None
        # When the detecting sources last became unavailable (the model start counts).
        self._binary_lost = now
        self._power_lost = now
        self._power: float | None = None
        self._power_time: datetime | None = None
        self._last_energy: float | None = None
        self._last_increase: datetime | None = None
        self._ring: list[tuple[datetime, float | None, float | None]] = []

        self._heating = False
        self._run_start: datetime | None = None
        self._run_energy = 0.0
        self._startup_used = 0.0
        self._run_start_avg = self.t_avg
        self._run_snapshot = IntervalSums()
        # Draws since the run started: (time, litres, kind), kind mixed, other or reclass.
        # A counter-timeout end is found late, and these are replayed after its charge.
        self._draw_log: list[tuple[datetime, float, str]] = []
        self._replaying = False

        self._sums = IntervalSums()
        self._last_charge_temp: float | None = None
        # The sums at the last counter increase: a counter-timeout run end is found late, and
        # its closure uses the sums as of the run end.
        self._increase_sums: IntervalSums | None = None
        # When the last run ended: counter increases soon after it still belong to that run.
        self._last_run_end: datetime | None = None
        # Seconds each source was unavailable in this calibration interval, and since when the
        # sources that are unavailable now have been.
        self._unavailable: dict[str, float] = {}
        self._down_since: dict[str, datetime] = {}

        self.t_cold = self._cold_at(now)
        self._clamp()

    # ----- inputs -------------------------------------------------------------------------

    def on_water_meter(
        self, now: datetime, value: float | None, unit: str
    ) -> list[ModelEvent]:
        """Process a whole-house water meter reading.

        Args:
            now: Time of the reading.
            value: The meter reading in `unit`, None when unavailable or non-numeric.
            unit: The meter unit: m3, L, gal or ft3.

        Returns:
            The events the reading caused.
        """
        now, events = self._begin(now)
        self._mark("water_meter", _finite(value), now)
        result = self._classifier.on_meter(now, value, unit)
        self._collect_draw_end(now)
        if result is None:
            return events
        events += self._apply_reclassify(now, result.reclassified)
        events += self._apply_draw(now, result.litres, mixed=result.mixed)
        events += self._apply_sensor_bounds(now)
        self._last_draw = self._draw_record(now)
        return events

    def on_humidity(
        self, now: datetime, sensor_id: str, value: float | None
    ) -> list[ModelEvent]:
        """Process a bathroom humidity reading in percent."""
        now, events = self._begin(now)
        self._mark(f"humidity:{sensor_id}", _finite(value), now)
        reclassify = self._classifier.on_humidity(now, sensor_id, value)
        self._collect_draw_end(now)
        events += self._apply_reclassify(now, reclassify)
        events += self._apply_sensor_bounds(now)
        self._resnapshot_draw(now, reclassify)
        return events

    def on_energy(self, now: datetime, kwh: float | None) -> list[ModelEvent]:
        """Process a reading of the thermal energy counter in kWh.

        A decrease is a counter reset: no heat, and the reading is the new starting point.
        """
        now, events = self._begin(now)
        self._mark("energy_counter", _finite(kwh), now)
        if not _finite(kwh):
            return events
        last, self._last_energy = self._last_energy, float(kwh)
        if last is None or self._last_energy <= last:
            return events
        delta = self._last_energy - last
        self._last_increase = now
        self._increase_sums = replace(self._sums)
        self._draw_log.clear()
        events += self._evaluate_heating(now)
        if self._heating and self.sources.energy_counter:
            events += self._apply_heat(now, delta)
        elif self._counter_lag(now):
            # The counter reports the last step of a run after the run ended. The model has
            # charged already, so only the closure uses it.
            change = {"counter_lag_kwh": delta, "run_end": _iso(self._last_run_end)}
            events.append(self._record(now, EventKind.HEAT, change, self._temps()))
        return events

    def on_power(self, now: datetime, watts: float | None) -> list[ModelEvent]:
        """Process a reading of the heat power sensor in W.

        The energy is the previous reading times the time since it (left Riemann sum), while
        a run is active. A gap where the power was unavailable counts as no energy.
        """
        now, events = self._begin(now)
        self._mark("power", _finite(watts), now)
        events += self._integrate_power(now)
        if _finite(watts):
            self._power = float(watts)
        else:
            if self._power is not None:
                self._power_lost = now
            self._power = None
        self._power_time = now
        events += self._evaluate_heating(now)
        return events

    def on_heating(self, now: datetime, active: bool | None) -> list[ModelEvent]:
        """Process the heating-active binary sensor: True on, False off, None unavailable."""
        now, events = self._begin(now)
        self._mark("heating_binary", active is not None, now)
        if active is None and self._binary is not None:
            self._binary_lost = now
        self._binary = active
        events += self._evaluate_heating(now)
        events += self._follow_sensor(now)
        return events

    def on_flow_return(
        self, now: datetime, flow: float | None, ret: float | None
    ) -> list[ModelEvent]:
        """Process the heater's flow and return temperatures in C, read together.

        Either value None records a gap.
        """
        now, events = self._begin(now)
        self._mark("flow_return", _finite(flow) and _finite(ret), now)
        if _finite(flow) and _finite(ret):
            self._ring.append((now, float(flow), float(ret)))
        else:
            self._ring.append((now, None, None))
        cutoff = now - timedelta(seconds=_RING_RETENTION_SECONDS)
        # Keep the last reading before the cutoff: it is the value in effect at the window start.
        while len(self._ring) > 1 and self._ring[1][0] <= cutoff:
            self._ring.pop(0)
        return events

    def on_tank_sensor(self, now: datetime, value: float | None) -> list[ModelEvent]:
        """Process the tank temperature sensor in C, None when unavailable."""
        now, events = self._begin(now)
        self._mark("tank_sensor", _finite(value), now)
        self._tank_sensor = float(value) if _finite(value) else None
        events += self._follow_sensor(now)
        events += self._apply_sensor_bounds(now)
        return events

    def on_cold_water_sensor(
        self, now: datetime, value: float | None
    ) -> list[ModelEvent]:
        """Process the cold water temperature sensor in C, None when unavailable."""
        now, events = self._begin(now)
        self._mark("cold_sensor", _finite(value), now)
        self._cold_sensor = float(value) if _finite(value) else None
        events += self._refresh_cold(now)
        return events

    def on_ambient_sensor(self, now: datetime, value: float | None) -> list[ModelEvent]:
        """Process the ambient temperature sensor in C, None when unavailable."""
        now, events = self._begin(now)
        self._mark("ambient_sensor", _finite(value), now)
        if _finite(value):
            self._ambient_sensor = float(value)
            self._ambient_last = (self._ambient_sensor, now)
        else:
            if self._ambient_sensor is not None:
                # After a restore the outage began at the saved time, not at the restart.
                lost = self._ambient_restored or now
                self._ambient_last = (self._ambient_sensor, lost)
            self._ambient_sensor = None
        self._ambient_restored = None
        return events

    def tick(self, now: datetime) -> list[ModelEvent]:
        """Advance time: standing loss, run timeout, shower detection windows, sensor bounds.

        The runtime calls it at least every 5 minutes.
        """
        now, events = self._begin(now)
        reclassify = self._classifier.update(now)
        self._collect_draw_end(now)
        events += self._apply_reclassify(now, reclassify)
        events += self._follow_sensor(now)
        events += self._apply_sensor_bounds(now)
        self._resnapshot_draw(now, reclassify)
        return events

    def set_options(self, options: ModelOptions) -> None:
        """Use new tuning values. The state is kept."""
        self.options = options
        self._classifier.set_options(options.classifier_options())
        self.t_cold = self._cold_at(self._now)
        self._clamp()

    def set_state(
        self, now: datetime, t_avg: float | None = None, t_ch: float | None = None
    ) -> list[ModelEvent]:
        """Set the temperatures by hand (the `set_tank_state` action).

        With neither given, the tank is charged to the tank sensor's reading. The physical
        bounds apply, and the calibration interval starts again.

        Args:
            now: The time.
            t_avg: The new tank average in C, or None to keep it.
            t_ch: The new charged temperature in C, or None to keep it.

        Returns:
            The events: any caused by catching up to `now`, then the charge event.

        Raises:
            ValueError: Neither temperature is given and the tank sensor is unavailable.
        """
        now, events = self._begin(now)
        if t_avg is None and t_ch is None:
            if self._tank_sensor is None:
                raise ValueError("The tank sensor is unavailable")
            t_avg = t_ch = self._tank_sensor
        before = self._temps()
        if t_ch is not None:
            self.t_ch = t_ch
        if t_avg is not None:
            self.t_avg = t_avg
        self._clamp()
        self._bal_avg, self._bal_ch = self.t_avg, self.t_ch
        self._reset_interval(now)
        self._last_reset = now
        self._classifier.clear_pending()
        events.append(self._record(now, EventKind.CHARGE, {"manual": True}, before))
        return events

    def log_event(
        self,
        now: datetime,
        kind: EventKind,
        change: dict[str, Any],
        before: tuple[float, float] | None = None,
    ) -> ModelEvent:
        """Record an event that is not a model step, such as a calibration change.

        Args:
            now: The time of the event.
            kind: The kind of event.
            change: What changed, a JSON-compatible dict.
            before: T_avg and T_ch before the change, by default those now.

        Returns:
            The recorded event.
        """
        return self._record(
            now, kind, change, self._temps() if before is None else before
        )

    def forget_reading(self, source: str) -> None:
        """Forget the last reading of a counter, so that its next reading is a new start.

        For a source whose entity was replaced: the new entity's first reading must not count
        as a change since the old entity's last one.

        Args:
            source: `water_meter` or `energy_counter`.

        Raises:
            ValueError: The source has no baseline.
        """
        if source == "water_meter":
            self._classifier.forget_meter()
        elif source == "energy_counter":
            self._last_energy = None
        else:
            raise ValueError(f"No baseline for {source}")

    # ----- outputs ------------------------------------------------------------------------

    @property
    def cold_fraction(self) -> float:
        """Return f = (t_ch - t_avg) / (t_ch - t_cold), limited to 0-1, 0 if t_ch <= t_cold."""
        span = self.t_ch - self.t_cold
        if span <= 0:
            return 0.0
        return _clamp01((self.t_ch - self.t_avg) / span)

    @property
    def balance_cold_fraction(self) -> float:
        """Return f of the energy balance without the sensor bounds, limited to 0-1.

        It is `(t_ch - t_avg) / (t_ch - t_cold)` of the plain balance, which calibration uses
        to estimate the thermocline width.
        """
        span = self._bal_ch - self.t_cold
        if span <= 0:
            return 0.0
        return _clamp01((self._bal_ch - self._bal_avg) / span)

    @property
    def tank_sensor(self) -> float | None:
        """Return the last tank sensor reading in C, None when unavailable."""
        return self._tank_sensor

    def last_draw_end(self, now: datetime) -> DrawEnd | None:
        """Return the state at the end of the last draw, None when there was none.

        A running draw session counts as ending now: the record is built from the current
        state, with `now` as its time.
        """
        if self._classifier.session_active:
            return self._draw_record(now)
        return self._draw_end

    def unavailable_seconds(self, now: datetime) -> dict[str, float]:
        """Return the seconds each source was unavailable since the interval started."""
        result = dict(self._unavailable)
        for source, since in self._down_since.items():
            result[source] = result.get(source, 0.0) + max(
                0.0, (now - since).total_seconds()
            )
        return result

    @property
    def tank_litres_exact(self) -> float:
        """Return max(0, V * (u - f)) in litres, not rounded."""
        return max(
            0.0,
            self.options.volume * (self.options.usable_fraction - self.cold_fraction),
        )

    @property
    def shower_litres_exact(self) -> float:
        """Return the tank litres times (t_ch - t_cold) / (t_mix - t_cold), not rounded."""
        tank = self.tank_litres_exact
        lift = self.options.mix_temperature - self.t_cold
        if self.t_ch <= self.options.mix_temperature or lift <= 0:
            return tank
        return tank * (self.t_ch - self.t_cold) / lift

    @property
    def outputs(self) -> Outputs:
        """Return the four outputs with the rounding of the spec."""
        u = self.options.usable_fraction
        percent = _clamp01((u - self.cold_fraction) / u) * 100 if u > 0 else 0.0
        shower = self.shower_litres_exact
        return Outputs(
            tank_litres=_round_half_up(self.tank_litres_exact),
            shower_litres=_round_half_up(shower),
            percent_charged=_round_half_up(percent),
            shower_minutes=_round_half_up(shower / self.options.shower_flow),
        )

    @property
    def shower_detected(self) -> bool:
        """Return whether a shower or bath is detected."""
        return self._classifier.detected

    @property
    def detection_available(self) -> bool:
        """Return whether a detection method (humidity or the long-draw rule) is configured."""
        return bool(self.sources.humidity_sensors) or self.options.long_draw_minutes > 0

    @property
    def heating(self) -> bool:
        """Return whether a heating run is active."""
        return self._heating

    @property
    def interval_sums(self) -> IntervalSums:
        """Return a copy of the energy balance sums since the last charge."""
        return replace(self._sums)

    @property
    def events(self) -> list[ModelEvent]:
        """Return the event log, oldest first."""
        return list(self._events)

    def ambient_temperature(self, now: datetime) -> float:
        """Return t_ambient in use at a time.

        The sensor's reading while it is available; its last reading for `ambient_fallback`
        hours after it went unavailable; the `ambient_temperature` option otherwise.
        """
        if not self.sources.ambient_sensor:
            return self.options.ambient_temperature
        if self._ambient_sensor is not None:
            return self._ambient_sensor
        last = self._ambient_last
        if last is not None and now - last[1] < timedelta(
            hours=self.options.ambient_fallback
        ):
            return last[0]
        return self.options.ambient_temperature

    def cold_water_temperature(self, now: datetime) -> float:
        """Return t_cold at a time: the sensor when available, else the seasonal curve."""
        return self._cold_at(now)

    # ----- internals ----------------------------------------------------------------------

    def reset_since(self, time: datetime) -> bool:
        """Return whether T_avg was replaced after `time` (a charge or a manual set_state)."""
        return self._last_reset is not None and self._last_reset > time

    def _resnapshot_draw(self, now: datetime, reclassified: float) -> None:
        """Refresh the open session's record after a reclassification lowered T_avg."""
        if reclassified > 0 and self._last_draw is not None:
            if self._classifier.session_active:
                self._last_draw = replace(
                    self._draw_record(now), time=self._last_draw.time
                )

    def _draw_record(self, time: datetime) -> DrawEnd:
        """Return the current state as a draw end record at `time`."""
        return DrawEnd(
            time=time,
            cold_fraction=self.cold_fraction,
            t_ch=self.t_ch,
            t_avg=self.t_avg,
            t_cold=self.t_cold,
            tank_sensor=self._tank_sensor,
            usable_fraction=self.options.usable_fraction,
        )

    def _collect_draw_end(self, now: datetime) -> None:
        """Keep the record of a draw session that the classifier reports as ended.

        The record is the state after the session's last increase. When the model has no such
        state (the session began before a restart), it is the state now.
        """
        ended = self._classifier.take_session_end()
        if ended is None:
            return
        last = self._last_draw
        if last is None or last.time != ended:
            last = replace(self._draw_record(now), time=ended)
        self._draw_end = last
        self._last_draw = None

    def _mark(self, source: str, available: bool, now: datetime) -> None:
        """Track how long a source is unavailable within the calibration interval."""
        since = self._down_since.get(source)
        if available:
            if since is not None:
                seconds = max(0.0, (now - since).total_seconds())
                self._unavailable[source] = self._unavailable.get(source, 0.0) + seconds
                del self._down_since[source]
        elif since is None:
            self._down_since[source] = now

    def _counter_lag(self, now: datetime) -> bool:
        """Return whether a counter increase now belongs to the run that just ended."""
        end = self._last_run_end
        return (
            not self._heating
            and self.sources.energy_counter
            and end is not None
            and 0 <= (now - end).total_seconds() <= COUNTER_LAG_SECONDS
        )

    def _cold_at(self, now: datetime) -> float:
        """Return t_cold = mean - amplitude * cos(2 pi (doy - coldest_day) / 365)."""
        if self.sources.cold_sensor and self._cold_sensor is not None:
            return self._cold_sensor
        o = self.options
        day = now.timetuple().tm_yday
        return o.cold_mean - o.cold_amplitude * math.cos(
            2 * math.pi * (day - o.cold_coldest_day) / 365
        )

    def _temps(self) -> tuple[float, float]:
        """Return (t_avg, t_ch)."""
        return self.t_avg, self.t_ch

    def _clamp(self) -> None:
        """Keep t_cold <= t_avg <= t_ch <= t_max, for the model and the plain balance."""
        o = self.options
        self.t_ch = min(max(self.t_ch, self.t_cold), o.max_temperature)
        self.t_avg = min(max(self.t_avg, self.t_cold), self.t_ch)
        self._bal_ch = min(max(self._bal_ch, self.t_cold), o.max_temperature)
        self._bal_avg = min(max(self._bal_avg, self.t_cold), self._bal_ch)

    def _record(
        self,
        now: datetime,
        kind: EventKind,
        change: dict[str, Any],
        before: tuple[float, float],
    ) -> ModelEvent:
        """Create an event from the state before and now, and log it."""
        if self._replaying:
            change = {**change, "replayed": True}
        event = ModelEvent(
            time=now,
            kind=kind,
            change=change,
            t_avg_before=before[0],
            t_avg_after=self.t_avg,
            t_ch_before=before[1],
            t_ch_after=self.t_ch,
        )
        last = self._events[-1] if self._events else None
        if kind == EventKind.LOSS and last is not None and last.kind == EventKind.LOSS:
            # Quiet periods log one loss event per tick: merge them so draws stay in the log.
            hours = last.change["hours"] + change["hours"]
            self._events[-1] = replace(
                last,
                change={**change, "hours": hours},
                t_avg_after=event.t_avg_after,
                t_ch_after=event.t_ch_after,
            )
        else:
            self._events.append(event)
        return event

    def _begin(self, now: datetime) -> tuple[datetime, list[ModelEvent]]:
        """Start every input: standing loss up to now, t_cold, bounds, an ended run.

        Returns:
            The time to use (never before the last one) and the events so far.
        """
        now = max(now, self._now)
        events = self._step_loss(now)
        events += self._refresh_cold(now)
        events += self._evaluate_heating(now)
        return now, events

    def _step_loss(self, now: datetime) -> list[ModelEvent]:
        """Apply standing loss from the last step to `now`: t -= k * (t - t_ambient) * dt."""
        hours = (now - self._now).total_seconds() / 3600
        self._now = max(now, self._now)
        if hours <= 0:
            return []
        before = self._temps()
        o = self.options
        factor = min(1.0, o.loss_coefficient * hours)
        amb = self.ambient_temperature(now)
        self._sums.hours += hours
        self._sums.loss += max(0.0, self._bal_avg - amb) * hours
        self.t_avg -= factor * max(0.0, self.t_avg - amb)
        self.t_ch -= factor * max(0.0, self.t_ch - amb)
        self._bal_avg -= factor * max(0.0, self._bal_avg - amb)
        self._bal_ch -= factor * max(0.0, self._bal_ch - amb)
        if self._temps() == before:
            return []
        return [self._record(now, EventKind.LOSS, {"hours": hours}, before)]

    def _refresh_cold(self, now: datetime) -> list[ModelEvent]:
        """Update t_cold and keep the bounds. A clamp it causes is logged as a sensor bound."""
        before = self._temps()
        self.t_cold = self._cold_at(now)
        self._clamp()
        if self._temps() == before:
            return []
        change = {"rules": ["t_cold_clamp"], "t_cold": self.t_cold}
        return [self._record(now, EventKind.SENSOR_BOUND, change, before)]

    def _apply_draw(self, now: datetime, dv: float, *, mixed: bool) -> list[ModelEvent]:
        """Take the energy of a draw of `dv` litres: dt_avg = -dv * lift / V, in K."""
        before = self._temps()
        drop = (
            self._mixed_drop(dv, self.t_ch)
            if mixed
            else self._other_drop(dv, self.t_ch)
        )
        bal_drop = (
            self._mixed_drop(dv, self._bal_ch)
            if mixed
            else self._other_drop(dv, self._bal_ch)
        )
        self.t_avg -= drop
        self._bal_avg -= bal_drop
        if mixed:
            self._sums.mixed += bal_drop
        else:
            self._sums.other += self._other_drop(dv, self._bal_ch, share=1.0)
        self._clamp()
        if self._heating:
            self._draw_log.append((now, dv, "mixed" if mixed else "other"))
        change = {"litres": dv, "mixed": mixed}
        return [self._record(now, EventKind.DRAW, change, before)]

    def _apply_reclassify(self, now: datetime, dv: float) -> list[ModelEvent]:
        """Correct the model by the energy difference of `dv` litres that turned out mixed."""
        if dv <= 0:
            return []
        before = self._temps()
        self.t_avg -= self._mixed_drop(dv, self.t_ch) - self._other_drop(dv, self.t_ch)
        self._bal_avg -= self._mixed_drop(dv, self._bal_ch) - self._other_drop(
            dv, self._bal_ch
        )
        self._sums.mixed += self._mixed_drop(dv, self._bal_ch)
        self._sums.other -= self._other_drop(dv, self._bal_ch, share=1.0)
        self._clamp()
        if self._heating:
            self._draw_log.append((now, dv, "reclass"))
        return [self._record(now, EventKind.DRAW, {"reclassified_litres": dv}, before)]

    def _mixed_drop(self, dv: float, t_ch: float) -> float:
        """Return the drop of a mixed draw in K: dv * (min(t_mix, t_ch) - t_cold) / V."""
        lift = min(self.options.mix_temperature, t_ch) - self.t_cold
        return max(0.0, dv * lift) / self.options.volume

    def _other_drop(self, dv: float, t_ch: float, share: float | None = None) -> float:
        """Return the drop of an other draw in K: share * dv * (t_ch - t_cold) / V."""
        share = self.options.other_hot_share if share is None else share
        return share * dv * max(0.0, t_ch - self.t_cold) / self.options.volume

    def _apply_heat(self, now: datetime, de: float) -> list[ModelEvent]:
        """Raise t_avg by de * 1000 / (1.163 * V) K for `de` kWh, after the start-up energy."""
        before = self._temps()
        de = max(0.0, de)
        self._run_energy += de
        skipped = min(de, max(0.0, self.options.startup_energy - self._startup_used))
        self._startup_used += skipped
        rise = (de - skipped) * 1000 / (WATER_HEAT_CAPACITY_WH * self.options.volume)
        self.t_avg += rise
        self.t_ch = max(self.t_ch, self.t_avg)
        self._bal_avg += rise
        self._bal_ch = max(self._bal_ch, self._bal_avg)
        self._clamp()
        change = {"energy_kwh": de, "startup_used_kwh": skipped, "t_avg_rise": rise}
        return [self._record(now, EventKind.HEAT, change, before)]

    def _integrate_power(self, now: datetime) -> list[ModelEvent]:
        """Apply the energy of the heat power since its last reading (left Riemann sum).

        Only while a run is active and power is the energy source: de = P * dt, P in W, dt in h.
        """
        src = self.sources
        if (
            not self._heating
            or not src.power
            or src.energy_counter
            or self._power is None
            or self._power_time is None
        ):
            return []
        hours = max(0.0, (now - self._power_time).total_seconds()) / 3600
        self._power_time = now
        if hours <= 0:
            return []
        return self._apply_heat(now, self._power * hours / 1000)

    def _follow_sensor(self, now: datetime) -> list[ModelEvent]:
        """Without a heat input, rise to the tank sensor while heating is active."""
        t_s = self._tank_sensor
        src = self.sources
        if not self._heating or src.energy_counter or src.power or t_s is None:
            return []
        if t_s <= self.t_avg and t_s <= self.t_ch:
            return []
        before = self._temps()
        self.t_avg = max(self.t_avg, t_s)
        self.t_ch = max(self.t_ch, t_s)
        self._bal_avg = max(self._bal_avg, t_s)
        self._bal_ch = max(self._bal_ch, t_s)
        self._clamp()
        return [self._record(now, EventKind.HEAT, {"sensor": t_s}, before)]

    def _apply_sensor_bounds(self, now: datetime) -> list[ModelEvent]:
        """Apply the sensor rules of D5 while heating is not active."""
        t_s = self._tank_sensor
        if t_s is None or self._heating:
            return []
        o = self.options
        h = o.sensor_height
        w = o.thermocline_width
        delta = o.sensor_tolerance
        before = self._temps()
        rules: list[str] = []
        if t_s > self.t_ch + delta:
            # Heat the model did not see: t_ch to the sensor, t_avg by the same step.
            step = t_s - self.t_ch
            self.t_ch = t_s
            self.t_avg += step
            rules.append("raise_t_ch")
        self._clamp()
        span = self.t_ch - self.t_cold
        if span > 0:
            # h - w / 2 and h + w / 2, limited to 0-1.
            f_lo = _clamp01(h - w / 2)
            f_hi = _clamp01(h + w / 2)
            if t_s >= self.t_ch - delta:
                # The cold layer is below the sensor: f <= f_lo.
                floor = self.t_ch - f_lo * span
                if self.t_avg < floor:
                    self.t_avg = floor
                    rules.append("lower_bound")
            elif t_s <= self.t_cold + delta:
                # The cold layer has passed the sensor: f >= f_hi.
                cap = self.t_ch - f_hi * span
                if self.t_avg > cap:
                    self.t_avg = cap
                    rules.append("cold_cap")
            else:
                # The thermocline is at the sensor: s = (t_s - t_cold) / (t_ch - t_cold),
                # f_s = f_hi - s * (f_hi - f_lo), t_s_avg = t_ch - f_s * (t_ch - t_cold).
                s = (t_s - self.t_cold) / span
                f_s = f_hi - s * (f_hi - f_lo)
                t_s_avg = self.t_ch - f_s * span
                cap = t_s_avg + o.sensor_margin
                if self.t_avg > cap:
                    self.t_avg = cap
                    rules.append("thermocline_cap")
        self._clamp()
        if not rules:
            return []
        return [
            self._record(
                now, EventKind.SENSOR_BOUND, {"rules": rules, "sensor": t_s}, before
            )
        ]

    # ----- heating runs -------------------------------------------------------------------

    def _decide(self, now: datetime) -> tuple[bool, datetime] | None:
        """Ask the first configured detector that can decide whether heating is active.

        An unavailable detector holds the heating state (None) for 15 minutes, then the next
        configured one decides until it returns.

        Returns:
            (active, t_end), where t_end is when a run would have ended, or None to hold.
        """
        src = self.sources
        hold = timedelta(seconds=DETECTOR_HOLD_SECONDS)
        if src.heating_binary:
            if self._binary is not None:
                return bool(self._binary), now
            if now - self._binary_lost < hold:
                return None
        if src.power:
            if self._power is not None:
                return self._power > self.options.power_threshold, now
            if now - self._power_lost < hold:
                return None
        if src.energy_counter:
            last = self._last_increase
            if last is None:
                return False, now
            timeout = timedelta(seconds=HEATING_TIMEOUT_SECONDS)
            # The timeout only finds the end: the run ended at the last increase.
            if self._run_start is not None:
                last = max(last, self._run_start)
            return now - self._last_increase < timeout, last
        return None

    def _evaluate_heating(self, now: datetime) -> list[ModelEvent]:
        """Start or end a heating run when the detecting source says so."""
        decision = self._decide(now)
        if decision is None:
            return []
        active, t_end = decision
        if active and not self._heating:
            self._start_run(now)
        elif not active and self._heating:
            return self._end_run(now, t_end)
        return []

    def _start_run(self, now: datetime) -> None:
        """Start a heating run and remember the state the calibration interval ends in."""
        self._heating = True
        self._run_start = now
        self._run_energy = 0.0
        self._startup_used = 0.0
        self._run_start_avg = self.t_avg
        self._run_snapshot = replace(self._sums)
        self._draw_log.clear()
        if self._power is not None:
            # Power before the run start is not part of the run.
            self._power_time = now

    def _charge_temperature(self, t_end: datetime) -> tuple[float | None, str]:
        """Return the charged temperature and its source.

        The highest mean of flow and return over the last 2 minutes before the run ended,
        else the tank sensor.
        """
        if self.sources.flow_return:
            start = t_end - timedelta(seconds=CHARGE_WINDOW_SECONDS)
            samples: list[tuple[float | None, float | None]] = []
            prior: tuple[float | None, float | None] | None = None
            for time, flow, ret in self._ring:
                if time <= start:
                    prior = (flow, ret)
                elif time <= t_end:
                    samples.append((flow, ret))
            if prior is not None:
                samples.insert(0, prior)
            means = [(f + r) / 2 for f, r in samples if f is not None and r is not None]
            if means:
                return max(means), "flow_return"
        if self._tank_sensor is not None:
            return self._tank_sensor, "tank_sensor"
        return None, "none"

    def _end_run(self, now: datetime, t_end: datetime) -> list[ModelEvent]:
        """End the run: T_avg = T_ch = the charged temperature."""
        events = self._integrate_power(now)
        before = self._temps()
        charge, source = self._charge_temperature(t_end)
        run_sums = self._run_sums(t_end, now)
        change: dict[str, Any] = {
            "charge_temperature": charge,
            "source": source,
            "run_start": _iso(self._run_start),
            "run_end": t_end.isoformat(),
            "run_energy_kwh": self._run_energy,
            "startup_used_kwh": self._startup_used,
            "startup_energy_kwh": self.options.startup_energy,
            "run_start_t_avg": self._run_start_avg,
            "previous_charge_temperature": self._last_charge_temp,
            "interval": self._run_snapshot.as_dict(),
            "run": run_sums.as_dict(),
            "unavailable_seconds": self.unavailable_seconds(now),
        }
        late = [entry for entry in self._draw_log if entry[0] > t_end]
        self._draw_log.clear()
        self._heating = False
        self._run_start = None
        self._run_energy = 0.0
        self._startup_used = 0.0
        self._last_run_end = t_end
        if charge is None:
            # Nothing to charge to: the closure is not valid, so the interval starts again.
            self._reset_interval(now)
            self._classifier.clear_pending(until=t_end)
            return [*events, self._record(now, EventKind.CHARGE, change, before)]
        self.t_avg = self.t_ch = self._bal_avg = self._bal_ch = charge
        self._clamp()
        self._last_reset = now
        self._reset_interval(now)
        self._classifier.clear_pending(until=t_end)
        self._last_charge_temp = self.t_ch
        events.append(self._record(now, EventKind.CHARGE, change, before))
        return events + self._replay_late_draws(now, t_end, late)

    def _run_sums(self, t_end: datetime, now: datetime) -> IntervalSums:
        """Return the balance sums of the run: from its start to `t_end`.

        A counter-timeout end is found late, so the sums are those taken at the last counter
        increase. They hold the in-run draws and loss that the closure equation needs.
        """
        start = self._run_snapshot
        if t_end >= now:
            end = self._sums
        elif t_end == self._last_increase and self._increase_sums is not None:
            end = self._increase_sums
        else:
            end = start
        return IntervalSums(
            hours=max(0.0, end.hours - start.hours),
            loss=end.loss - start.loss,
            other=end.other - start.other,
            mixed=end.mixed - start.mixed,
        )

    def _replay_late_draws(
        self, now: datetime, t_end: datetime, late: list[tuple[datetime, float, str]]
    ) -> list[ModelEvent]:
        """Apply loss and draws between a run end and the moment it was found to the new charge.

        A counter timeout finds the end late. The charge as of the run end overwrote what
        happened since, so replay it from the run end, into the new interval.
        """
        if t_end >= now:
            return []
        self._now = t_end
        events: list[ModelEvent] = []
        # Other-draw litres after the run end that a detection can still reclassify.
        window = timedelta(minutes=self.options.reclassify_window)
        others: list[tuple[datetime, float]] = []
        self._replaying = True
        try:
            for time, dv, kind in late:
                events += self._step_loss(time)
                if kind == "reclass":
                    # Only litres after the run end: the charge already reflects the rest.
                    dv = sum(amount for t, amount in others if t >= time - window)
                    others.clear()
                    events += self._apply_reclassify(time, dv)
                else:
                    if kind == "other":
                        others.append((time, dv))
                    events += self._apply_draw(time, dv, mixed=kind == "mixed")
            events += self._step_loss(now)
        finally:
            self._replaying = False
        return events

    def _reset_interval(self, now: datetime) -> None:
        """Start a new calibration interval at `now`."""
        self._sums = IntervalSums()
        self._last_charge_temp = None
        self._run_snapshot = IntervalSums()
        self._increase_sums = None
        self._unavailable = {}
        self._down_since = dict.fromkeys(self._down_since, now)

    # ----- persistence --------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the full model state as a JSON-compatible dict (options are not included)."""
        return {
            "version": STATE_VERSION,
            "t_avg": self.t_avg,
            "t_ch": self.t_ch,
            "bal_avg": self._bal_avg,
            "bal_ch": self._bal_ch,
            "now": self._now.isoformat(),
            "tank_sensor": self._tank_sensor,
            "cold_sensor": self._cold_sensor,
            "ambient_sensor": self._ambient_sensor,
            "ambient_last": None
            if self._ambient_last is None
            else {
                "value": self._ambient_last[0],
                "time": self._ambient_last[1].isoformat(),
            },
            "binary": self._binary,
            "power": self._power,
            "draw_log": [[t.isoformat(), dv, kind] for t, dv, kind in self._draw_log],
            "binary_lost": self._binary_lost.isoformat(),
            "power_lost": self._power_lost.isoformat(),
            "last_energy": self._last_energy,
            "last_increase": _iso(self._last_increase),
            "ring": [[t.isoformat(), f, r] for t, f, r in self._ring],
            "heating": self._heating,
            "run_start": _iso(self._run_start),
            "run_energy": self._run_energy,
            "startup_used": self._startup_used,
            "run_start_avg": self._run_start_avg,
            "run_snapshot": self._run_snapshot.as_dict(),
            "sums": self._sums.as_dict(),
            "last_charge_temp": self._last_charge_temp,
            "increase_sums": None
            if self._increase_sums is None
            else self._increase_sums.as_dict(),
            "last_run_end": _iso(self._last_run_end),
            "unavailable": self._unavailable,
            "down_since": {s: t.isoformat() for s, t in self._down_since.items()},
            "classifier": self._classifier.to_dict(),
            "draw_end": None if self._draw_end is None else self._draw_end.as_dict(),
            "last_draw": None if self._last_draw is None else self._last_draw.as_dict(),
            "last_reset": _iso(self._last_reset),
        }

    @classmethod
    def from_dict(
        cls,
        options: ModelOptions,
        sources: Sources,
        data: dict[str, Any],
        *,
        max_events: int = 500,
    ) -> TankModel:
        """Restore a model from `to_dict` output.

        Args:
            options: The tuning values now in force.
            sources: Which sources are configured now.
            data: A dict produced by `to_dict`.
            max_events: Size of the event log, which starts empty.

        Returns:
            The restored model.

        Raises:
            ValueError: The data is malformed or from an unknown version.
        """
        try:
            if data["version"] != STATE_VERSION:
                raise ValueError(f"Unknown model state version {data['version']}")
            model = cls(
                options,
                sources,
                datetime.fromisoformat(data["now"]),
                float(data["t_avg"]),
                float(data["t_ch"]),
                max_events=max_events,
                # A source that is no longer configured has no say: its reading is dropped.
                cold_sensor=data["cold_sensor"] if sources.cold_sensor else None,
                ambient_sensor=data.get("ambient_sensor")
                if sources.ambient_sensor
                else None,
            )
            # Added with the ambient sensor: older saved states lack it.
            if sources.ambient_sensor:
                if (last := data.get("ambient_last")) is not None:
                    model._ambient_last = (
                        float(last["value"]),
                        datetime.fromisoformat(last["time"]),
                    )
                if model._ambient_sensor is not None:
                    model._ambient_restored = model._now
            model._bal_avg = float(data["bal_avg"])
            model._bal_ch = float(data["bal_ch"])
            model._tank_sensor = data["tank_sensor"]
            model._binary = data["binary"]
            model._power = data["power"]
            # The power integration start is not restored: it restarts at the first reading,
            # so downtime adds no energy.
            model._draw_log = [
                (datetime.fromisoformat(t), float(dv), kind)
                for t, dv, kind in data["draw_log"]
            ]
            model._binary_lost = datetime.fromisoformat(data["binary_lost"])
            model._power_lost = datetime.fromisoformat(data["power_lost"])
            model._last_energy = data["last_energy"]
            model._last_increase = _from_iso(data["last_increase"])
            model._ring = [
                (datetime.fromisoformat(t), f, r) for t, f, r in data["ring"]
            ]
            model._heating = bool(data["heating"])
            model._run_start = _from_iso(data["run_start"])
            model._run_energy = float(data["run_energy"])
            model._startup_used = float(data["startup_used"])
            model._run_start_avg = float(data["run_start_avg"])
            model._run_snapshot = IntervalSums.from_dict(data["run_snapshot"])
            model._sums = IntervalSums.from_dict(data["sums"])
            model._last_charge_temp = data["last_charge_temp"]
            # Added with the calibration bookkeeping: older saved states lack them.
            if data.get("increase_sums") is not None:
                model._increase_sums = IntervalSums.from_dict(data["increase_sums"])
            model._last_run_end = _from_iso(data.get("last_run_end"))
            model._unavailable = {
                s: float(v) for s, v in data.get("unavailable", {}).items()
            }
            model._down_since = {
                s: datetime.fromisoformat(t)
                for s, t in data.get("down_since", {}).items()
            }
            model._classifier.restore(data["classifier"])
            # Added with "Hot water ran out": older saved states lack it.
            if (draw_end := data.get("draw_end")) is not None:
                model._draw_end = DrawEnd.from_dict(draw_end)
            model._last_reset = _from_iso(data.get("last_reset"))
            if (last_draw := data.get("last_draw")) is not None:
                model._last_draw = DrawEnd.from_dict(last_draw)
            model._clamp()
        except (KeyError, TypeError, AttributeError) as err:
            raise ValueError(f"Invalid model state: {err}") from err
        return model


__all__ = [
    "DrawEnd",
    "EventKind",
    "IntervalSums",
    "ModelEvent",
    "ModelOptions",
    "Outputs",
    "Sources",
    "TankModel",
]
