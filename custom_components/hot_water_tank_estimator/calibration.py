"""Calibration: charge closures, the fitter, quiet-window loss and the thermocline width.

Pure Python: standard library only, no Home Assistant imports and no I/O. The formulas and
their symbols are those of `docs/model.md`:

- `C = 1.163 * V / 1000` is the heat capacity of the tank in kWh per K.
- At the end of a heating run the tank is evenly mixed at `t_charge`, so the average at the
  start of the run follows from the run's energy `E_run` (kWh), the start-up energy `S` (kWh)
  and the draws and loss during the run:

      t_true_start = t_charge - (E_run - S) / C + mixed_run + share * other_run + k * loss_run

- Between two charges the energy balance without the sensor bounds gives

      t_ch_prev - t_true_start = k * loss + share * other + mixed

  Both equations together are linear in `k`, `share` and `S`, which the fitter solves over the
  stored intervals. `loss`, `other` and `mixed` are the sums of the whole period from one charge
  to the next (the interval before the run plus the run).

A `Calibrator` watches a `TankModel` through the events its inputs return, builds one `Closure`
per heating run and learns the parameters. The caller applies `Calibrator.options` to the model
with `TankModel.set_options` whenever `observe` returns True.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from .const import COUNTER_LAG_SECONDS, WATER_HEAT_CAPACITY_WH
from .model import EventKind, ModelEvent, ModelOptions, TankModel

# The learned parameters, named as the `ModelOptions` fields, with their bounds.
OTHER_HOT_SHARE = "other_hot_share"
STARTUP_ENERGY = "startup_energy"
LOSS_COEFFICIENT = "loss_coefficient"
THERMOCLINE_WIDTH = "thermocline_width"
USABLE_FRACTION = "usable_fraction"

PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    OTHER_HOT_SHARE: (0.0, 0.6),
    STARTUP_ENERGY: (0.0, 3.0),  # kWh
    LOSS_COEFFICIENT: (0.001, 0.015),  # per hour
    THERMOCLINE_WIDTH: (0.1, 0.6),
    USABLE_FRACTION: (0.5, 0.98),
}
# The three parameters of the closure fit.
CLOSURE_PARAMETERS = (LOSS_COEFFICIENT, OTHER_HOT_SHARE, STARTUP_ENERGY)

# Where a parameter's value in use comes from.
SOURCE_OPTION = "option"
SOURCE_SETUP_FIT = "setup_fit"
SOURCE_LEARNED = "learned"
SOURCE_LOCKED = "locked"

FORGETTING_FACTOR = 0.95  # weight of an interval relative to the next one
MIN_INTERVALS = 5  # intervals needed before the closure fit is applied
MIN_RUN_MINUTES = 15.0  # shorter runs do not mix the tank
MAX_UNAVAILABLE_FRACTION = 0.1  # of an interval, for any one source
QUIET_WINDOW_HOURS = 5.0  # shortest window for a loss estimate
QUIET_KEEP = 10  # loss estimates from quiet windows that are averaged
QUIET_MIN_ESTIMATES = 3  # estimates whose mean is held as k by the closure fit
QUIET_SETTLE_HOURS = (
    1.0  # a quiet window opens this long after a run end at the earliest
)
WIDTH_KEEP = 10  # width estimates that are averaged
WIDTH_MIN_ESTIMATES = 3  # estimates needed before the width is applied
MAX_CLOSURES = 100  # closures kept, newest last

# Closure status.
CLOSURE = "closure"  # a valid interval: part of the fit and of the error statistics
SENSOR_START = (
    "sensor_start"  # no known charge before it: the model started from the sensor
)
EXCLUDED = "excluded"  # see `Closure.reason`

# Reasons for an excluded closure (`source_unavailable` is followed by `:<source>`).
REASON_NO_CHARGE = "no_charge_temperature"
REASON_AFTER_NO_CHARGE = "after_no_charge_temperature"
REASON_AFTER_RESET = "after_manual_reset"
REASON_SHORT_RUN = "short_run"
REASON_UNAVAILABLE = "source_unavailable"


def heat_capacity(volume: float) -> float:
    """Return C = 1.163 * V / 1000 in kWh per K for a tank of `volume` litres."""
    return WATER_HEAT_CAPACITY_WH * volume / 1000


@dataclass(frozen=True)
class Closure:
    """One heating run and the interval that ends in it.

    The sums are the energy balance without sensor bounds. `loss`, `other` and `mixed` cover
    the whole period from the previous charge to the end of the run, the `_run` figures only
    the run itself.

    Attributes:
        run_start: When the run started.
        run_end: When the run ended (the last counter increase for a counter timeout).
        t_charge: The charged temperature in C, None when no source gave one.
        t_ch_prev: The charged temperature at the previous charge in C, None when unknown.
        run_start_t_avg: The model's tank average at the run start in C.
        energy_kwh: The run's energy `E_run` in kWh, including counter increases after its end.
        startup_kwh: The start-up energy `S` in use, in kWh.
        share: The other-draws hot share in use.
        loss_coefficient: The loss coefficient `k` in use, per hour.
        volume: The tank volume in litres.
        hours: Hours from the previous charge to the end of the run.
        loss: Sum of `(t_avg - t_ambient) * dt` in K*h.
        other: Sum of the other-draw drops for a share of 1, in K.
        mixed: Sum of the mixed-draw drops, in K.
        loss_run: The part of `loss` inside the run, in K*h.
        other_run: The part of `other` inside the run, in K.
        mixed_run: The part of `mixed` inside the run, in K.
        status: `CLOSURE`, `SENSOR_START` or `EXCLUDED`.
        reason: Why the closure is excluded (or a sensor start is not a closure).
        error: The charge error in K: the model's tank average at the run start minus the true
            one. None when there is no charged temperature.
    """

    run_start: datetime | None
    run_end: datetime
    t_charge: float | None
    t_ch_prev: float | None
    run_start_t_avg: float
    energy_kwh: float
    startup_kwh: float
    share: float
    loss_coefficient: float
    volume: float
    hours: float
    loss: float
    other: float
    mixed: float
    loss_run: float
    other_run: float
    mixed_run: float
    status: str
    reason: str | None = None
    error: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the closure as a JSON-compatible dict."""
        data = {name: getattr(self, name) for name in _CLOSURE_FIELDS}
        data["run_start"] = (
            None if self.run_start is None else self.run_start.isoformat()
        )
        data["run_end"] = self.run_end.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Closure:
        """Create a closure from `as_dict` output."""
        values = dict(data)
        start = values["run_start"]
        values["run_start"] = None if start is None else datetime.fromisoformat(start)
        values["run_end"] = datetime.fromisoformat(values["run_end"])
        return cls(**{name: values[name] for name in _CLOSURE_FIELDS})


_CLOSURE_FIELDS = tuple(Closure.__dataclass_fields__)


def true_start_average(
    closure: Closure, startup: float, share: float, loss_coefficient: float
) -> float | None:
    """Return the true tank average at the run start in C, None without a charged temperature.

    `t_charge - (E_run - S) / C + mixed_run + share * other_run + k * loss_run`.

    Args:
        closure: The run and its sums.
        startup: The start-up energy `S` in kWh.
        share: The other-draws hot share.
        loss_coefficient: The loss coefficient `k` per hour.
    """
    if closure.t_charge is None:
        return None
    return (
        closure.t_charge
        - (closure.energy_kwh - startup) / heat_capacity(closure.volume)
        + closure.mixed_run
        + share * closure.other_run
        + loss_coefficient * closure.loss_run
    )


def charge_error(
    closure: Closure, startup: float, share: float, loss_coefficient: float
) -> float | None:
    """Return the charge error in K: the model's tank average at the run start minus the true one."""
    true_start = true_start_average(closure, startup, share, loss_coefficient)
    return None if true_start is None else closure.run_start_t_avg - true_start


def bounded_step(name: str, current: float, target: float) -> float:
    """Return a parameter after one update: the target within the bounds, one step at most.

    A step is a quarter of the bound range.

    Args:
        name: The parameter, a key of `PARAMETER_BOUNDS`.
        current: The value in use.
        target: The value the fit or estimate gives.
    """
    low, high = PARAMETER_BOUNDS[name]
    target = min(max(target, low), high)
    limit = (high - low) / 4
    return current + min(max(target - current, -limit), limit)


def fit_closures(
    closures: Sequence[Closure],
    in_use: Mapping[str, float],
    locks: Iterable[str] = (),
    forgetting: float = FORGETTING_FACTOR,
) -> dict[str, float] | None:
    """Fit the loss coefficient, the share and the start-up energy to the closures.

    The equation of each closure is

        t_ch_prev - t_charge + E_run / C - mixed = k * loss + share * other + S / C

    with the totals over the interval and the run. It is solved by weighted least squares, the
    newest closure at weight 1 and each older one `forgetting` times the next. A locked
    parameter stays at its value in `in_use` and leaves the unknowns.

    Args:
        closures: The valid closures, oldest first.
        in_use: The values in use, for the locked parameters.
        locks: The locked parameters.
        forgetting: The weight of a closure relative to the next one.

    Returns:
        The fitted values, not yet limited by the bounds or the step, or None when there is
        nothing to fit or the equations do not determine the unknowns.
    """
    locked = set(locks)
    unknowns = [name for name in CLOSURE_PARAMETERS if name not in locked]
    if not unknowns or not closures:
        return None
    count = len(closures)
    rows: list[tuple[float, list[float], float]] = []
    for index, closure in enumerate(closures):
        if closure.t_charge is None or closure.t_ch_prev is None:
            continue
        capacity = heat_capacity(closure.volume)
        features = {
            LOSS_COEFFICIENT: closure.loss,
            OTHER_HOT_SHARE: closure.other,
            STARTUP_ENERGY: 1 / capacity,
        }
        y = (
            closure.t_ch_prev
            - closure.t_charge
            + closure.energy_kwh / capacity
            - closure.mixed
        )
        for name in locked & set(CLOSURE_PARAMETERS):
            y -= in_use[name] * features[name]
        rows.append(
            (
                forgetting ** (count - 1 - index),
                [features[name] for name in unknowns],
                y,
            )
        )
    if not rows:
        return None
    # Scale each column to unit weighted size so the elimination is well conditioned.
    scales = []
    for column in range(len(unknowns)):
        size = sum(w * row[column] ** 2 for w, row, _ in rows) ** 0.5
        if size <= 0:
            return None
        scales.append(size)
    size = len(unknowns)
    matrix = [[0.0] * size for _ in range(size)]
    vector = [0.0] * size
    for weight, row, y in rows:
        scaled = [value / scale for value, scale in zip(row, scales, strict=True)]
        for i in range(size):
            vector[i] += weight * scaled[i] * y
            for j in range(size):
                matrix[i][j] += weight * scaled[i] * scaled[j]
    solution = _solve(matrix, vector)
    if solution is None:
        return None
    return {
        name: value / scale
        for name, value, scale in zip(unknowns, solution, scales, strict=True)
    }


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Solve `matrix @ x = vector` by Gaussian elimination, None when it is singular."""
    size = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-9:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, size):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, size + 1):
                rows[r][c] -= factor * rows[col][c]
    solution = [0.0] * size
    for r in range(size - 1, -1, -1):
        total = rows[r][size] - sum(
            rows[r][c] * solution[c] for c in range(r + 1, size)
        )
        solution[r] = total / rows[r][r]
    return solution


@dataclass
class _Pending:
    """A run that has ended and may still receive counter increases (the counter lag)."""

    change: dict[str, Any]  # the charge event's figures
    run_end: datetime
    energy_kwh: float
    status: str
    reason: str | None

    def as_dict(self) -> dict[str, Any]:
        """Return the waiting run as a JSON-compatible dict."""
        return {
            "change": self.change,
            "run_end": self.run_end.isoformat(),
            "energy_kwh": self.energy_kwh,
            "status": self.status,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> _Pending:
        """Create the waiting run from `as_dict` output."""
        return cls(
            change=dict(data["change"]),
            run_end=datetime.fromisoformat(data["run_end"]),
            energy_kwh=float(data["energy_kwh"]),
            status=str(data["status"]),
            reason=data["reason"],
        )


@dataclass
class _QuietWindow:
    """A stretch with no draw and no heating while the sensor reads within the tolerance."""

    start: datetime
    first: float  # first sensor reading in C
    value: float  # reading in force in C
    since: datetime  # when `value` came in force
    integral: float = 0.0  # C*s of the readings before `since`


@dataclass
class Calibrator:
    """Builds charge closures from model events and learns the parameters.

    Attributes:
        base: The configured options. A learned value overrides its option unless locked.
        locks: The locked parameters: they keep their option value and are never learned.
        measures_heat: Whether an energy counter or power sensor is configured. Without one
            there are no closures, and the loss comes from quiet windows only.
        learn: Whether to change any parameter. False records the closures and errors only.
        label: The source recorded for a changed parameter, `learned` or `setup_fit`.
        values: The learned parameter values.
        sources: The source label of each learned parameter.
        closures: The closures, newest last, at most `MAX_CLOSURES`.
        quiet_estimates: The last loss coefficients from quiet windows.
        width_estimates: The last thermocline widths from first sensor drops.
    """

    base: ModelOptions
    locks: frozenset[str] = frozenset()
    measures_heat: bool = True
    learn: bool = True
    label: str = SOURCE_LEARNED
    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    closures: list[Closure] = field(default_factory=list)
    quiet_estimates: list[float] = field(default_factory=list)
    width_estimates: list[float] = field(default_factory=list)
    _pending: _Pending | None = field(default=None, repr=False)
    _unknown_start: str | None = field(default=None, repr=False)
    _last_run_end: datetime | None = field(default=None, repr=False)
    _window: _QuietWindow | None = field(default=None, repr=False)
    _drop: str | None = field(default=None, repr=False)

    # ----- parameters ---------------------------------------------------------------------

    @property
    def options(self) -> ModelOptions:
        """Return the options with the learned values applied (locked ones keep the option)."""
        learned = {n: v for n, v in self.values.items() if n not in self.locks}
        return replace(self.base, **learned)

    def source_of(self, name: str) -> str:
        """Return where the value of a parameter comes from: option, setup fit, learned, locked."""
        if name in self.locks:
            return SOURCE_LOCKED
        return (
            self.sources.get(name, SOURCE_OPTION)
            if name in self.values
            else SOURCE_OPTION
        )

    def value_of(self, name: str) -> float:
        """Return the value of a parameter in use."""
        return float(getattr(self.options, name))

    def set_base(self, base: ModelOptions, locks: Iterable[str] | None = None) -> None:
        """Use new configured options (and locks); the learned values stay."""
        self.base = base
        if locks is not None:
            self.set_locks(locks)

    def set_locks(self, locks: Iterable[str]) -> None:
        """Lock the given parameters. Removing a lock discards the value learned before it.

        A locked parameter keeps its option value. When its lock is removed the option value
        applies until the next fit, not a value learned long ago.
        """
        new = frozenset(locks)
        for name in self.locks - new:
            self.values.pop(name, None)
            self.sources.pop(name, None)
        self.locks = new

    def go_live(self) -> None:
        """Label further changes as learned instead of setup fit.

        The setup fit labels what it changes `setup_fit`. The runtime calls this once the fit
        is done, so a later update by live learning is reported as `learned`.
        """
        self.label = SOURCE_LEARNED

    def _apply(self, name: str, target: float) -> None:
        """Move a parameter towards `target`: within bounds, one step at most."""
        if not self.learn or name in self.locks:
            return
        current = self.value_of(name)
        value = bounded_step(name, current, target)
        if value != current:
            self.values[name] = value
            self.sources[name] = self.label

    # ----- statistics ---------------------------------------------------------------------

    @property
    def intervals(self) -> list[Closure]:
        """Return the valid closures, oldest first."""
        return [c for c in self.closures if c.status == CLOSURE]

    @property
    def sample_count(self) -> int:
        """Return the number of valid closures stored."""
        return len(self.intervals)

    @property
    def last_error(self) -> float | None:
        """Return the charge error of the newest valid closure in K."""
        errors = [c.error for c in self.intervals if c.error is not None]
        return errors[-1] if errors else None

    def mean_abs_error(self, last: int | None = 10) -> float | None:
        """Return the mean absolute charge error of the last valid closures in K."""
        errors = [abs(c.error) for c in self.intervals if c.error is not None]
        if last is not None:
            errors = errors[-last:]
        return sum(errors) / len(errors) if errors else None

    # ----- observing the model ------------------------------------------------------------

    def observe(
        self, model: TankModel, events: Sequence[ModelEvent], now: datetime
    ) -> bool:
        """Process what happened to the model, and learn from it.

        Call it after every model input and tick, with the events that call returned.

        Args:
            model: The model, in the state after the call.
            events: The events the call returned.
            now: The time of the call.

        Returns:
            Whether `options` changed, so the caller applies them with `set_options`.
        """
        before = self.options
        broke = False
        for event in events:
            broke = self._on_event(event) or broke
        self._finalize_due(now)
        self._track_quiet(model, now, broke=broke)
        self._track_drop(model)
        return self.options != before

    def flush(self) -> bool:
        """Finish the closure still waiting for counter increases. Returns whether options changed."""
        before = self.options
        self._finalize()
        return self.options != before

    def _on_event(self, event: ModelEvent) -> bool:
        """Handle one event. Returns whether it ends a quiet window."""
        change = event.change
        match event.kind:
            case EventKind.CHARGE:
                self._finalize()
                self._drop = None
                if "run_end" in change:
                    self._last_run_end = datetime.fromisoformat(change["run_end"])
                    self._on_charge(event)
                    self._drop = (
                        "armed" if change["charge_temperature"] is not None else None
                    )
                else:
                    # A manual reset: the next interval starts from a guessed state.
                    self._unknown_start = REASON_AFTER_RESET
                return True
            case EventKind.HEAT:
                lag = change.get("counter_lag_kwh")
                pending = self._pending
                if (
                    lag is not None
                    and pending is not None
                    and change["run_end"] == pending.run_end.isoformat()
                ):
                    pending.energy_kwh += lag
                return True
            case EventKind.DRAW:
                return True
        return False

    def _on_charge(self, event: ModelEvent) -> None:
        """Start the closure of a run that ended. It is finished after the counter lag."""
        if not self.measures_heat:
            return
        change = event.change
        status, reason = CLOSURE, None
        if change["charge_temperature"] is None:
            status, reason = EXCLUDED, REASON_NO_CHARGE
            self._unknown_start = REASON_AFTER_NO_CHARGE
        elif change["previous_charge_temperature"] is None:
            if self._unknown_start is None:
                status, reason = SENSOR_START, None
            else:
                status, reason = EXCLUDED, self._unknown_start
            self._unknown_start = None
        else:
            self._unknown_start = None
        self._pending = _Pending(
            change=change,
            run_end=datetime.fromisoformat(change["run_end"]),
            energy_kwh=change["run_energy_kwh"],
            status=status,
            reason=reason,
        )

    def _finalize_due(self, now: datetime) -> None:
        """Finish the waiting closure once the counter lag has passed."""
        pending = self._pending
        if pending is not None and now - pending.run_end > timedelta(
            seconds=COUNTER_LAG_SECONDS
        ):
            self._finalize()

    def _finalize(self) -> None:
        """Complete the waiting closure: exclusions, error, storage and the fit."""
        pending, self._pending = self._pending, None
        if pending is None:
            return
        change = pending.change
        interval, run = change["interval"], change["run"]
        options = self.options
        start = change["run_start"]
        run_start = None if start is None else datetime.fromisoformat(start)
        hours = interval["hours"] + run["hours"]
        status, reason = pending.status, pending.reason
        if status != EXCLUDED and run_start is not None:
            if (pending.run_end - run_start).total_seconds() < MIN_RUN_MINUTES * 60:
                status, reason = EXCLUDED, REASON_SHORT_RUN
        if status != EXCLUDED and hours > 0:
            source, seconds = max(
                change["unavailable_seconds"].items(),
                key=lambda item: item[1],
                default=("", 0.0),
            )
            if seconds > MAX_UNAVAILABLE_FRACTION * hours * 3600:
                status, reason = EXCLUDED, f"{REASON_UNAVAILABLE}:{source}"
        closure = Closure(
            run_start=run_start,
            run_end=pending.run_end,
            t_charge=change["charge_temperature"],
            t_ch_prev=change["previous_charge_temperature"],
            run_start_t_avg=change["run_start_t_avg"],
            energy_kwh=pending.energy_kwh,
            startup_kwh=options.startup_energy,
            share=options.other_hot_share,
            loss_coefficient=options.loss_coefficient,
            volume=options.volume,
            hours=hours,
            loss=interval["loss"] + run["loss"],
            other=interval["other"] + run["other"],
            mixed=interval["mixed"] + run["mixed"],
            loss_run=run["loss"],
            other_run=run["other"],
            mixed_run=run["mixed"],
            status=status,
            reason=reason,
        )
        error = charge_error(
            closure, closure.startup_kwh, closure.share, closure.loss_coefficient
        )
        self.add_closure(replace(closure, error=error))

    def add_closure(self, closure: Closure) -> None:
        """Store a finished closure and, if it is valid, refit the parameters."""
        self.closures.append(closure)
        del self.closures[:-MAX_CLOSURES]
        if closure.status == CLOSURE:
            self._fit()

    def _fit(self) -> None:
        """Refit the share, the start-up energy and the loss once enough intervals are stored."""
        intervals = self.intervals
        if len(intervals) < MIN_INTERVALS:
            return
        locks = set(self.locks)
        if (
            len(self.quiet_estimates) >= QUIET_MIN_ESTIMATES
            and LOSS_COEFFICIENT not in locks
        ):
            # Closures alone cannot separate k from the share: hold k at the quiet-window mean.
            # k in use steps towards it first, so share and S are not fitted against a k the
            # model does not use.
            self._apply(
                LOSS_COEFFICIENT, sum(self.quiet_estimates) / len(self.quiet_estimates)
            )
            locks.add(LOSS_COEFFICIENT)
        in_use = {name: self.value_of(name) for name in CLOSURE_PARAMETERS}
        fit = fit_closures(intervals, in_use, locks)
        if fit is None:
            return
        for name, value in fit.items():
            self._apply(name, value)

    # ----- loss from quiet windows --------------------------------------------------------

    def _track_quiet(self, model: TankModel, now: datetime, *, broke: bool) -> None:
        """Follow the quiet window: open it, extend it, or close it and estimate the loss."""
        window = self._window
        sensor = model.tank_sensor
        options = model.options
        ok = (
            not model.heating
            and sensor is not None
            and sensor >= model.t_ch - options.sensor_tolerance
        )
        if window is not None:
            window.integral += window.value * (now - window.since).total_seconds()
            window.since = now
            if broke or not ok:
                self._close_window(window, options.ambient_temperature)
                window = self._window = None
            elif sensor is not None:
                window.value = sensor
        settled = self._last_run_end is None or now - self._last_run_end >= timedelta(
            hours=QUIET_SETTLE_HOURS
        )
        if window is None and ok and settled and sensor is not None:
            self._window = _QuietWindow(now, sensor, sensor, now)

    def _close_window(self, window: _QuietWindow, ambient: float) -> None:
        """Estimate `k = rate / (t_mean - t_ambient)` from a window of at least 5 hours."""
        seconds = (window.since - window.start).total_seconds()
        hours = seconds / 3600
        if hours < QUIET_WINDOW_HOURS:
            return
        rate = (window.first - window.value) / hours  # K per hour
        mean = window.integral / seconds
        if rate <= 0 or mean <= ambient:
            return
        self.quiet_estimates.append(rate / (mean - ambient))
        del self.quiet_estimates[:-QUIET_KEEP]
        if (
            len(self.quiet_estimates) >= QUIET_MIN_ESTIMATES
            or not self.measures_heat
            or len(self.intervals) < MIN_INTERVALS
        ):
            # From 3 estimates the mean is k in use, and the closure fit holds it. With fewer,
            # the closure fit decides k once it has enough intervals.
            self._apply(
                LOSS_COEFFICIENT, sum(self.quiet_estimates) / len(self.quiet_estimates)
            )

    # ----- thermocline width from the first sensor drop -----------------------------------

    def _track_drop(self, model: TankModel) -> None:
        """Estimate `w = 2 * (h - f_e)` when the sensor first falls below `t_ch - delta`."""
        if model.heating:
            self._drop = None
            return
        sensor = model.tank_sensor
        if self._drop is None or self._drop == "done" or sensor is None:
            return
        options = model.options
        if sensor >= model.t_ch - options.sensor_tolerance:
            self._drop = "hot"
        elif self._drop == "hot":
            low, high = PARAMETER_BOUNDS[THERMOCLINE_WIDTH]
            estimate = 2 * (options.sensor_height - model.balance_cold_fraction)
            self.width_estimates.append(min(max(estimate, low), high))
            del self.width_estimates[:-WIDTH_KEEP]
            self._drop = "done"
            if len(self.width_estimates) >= WIDTH_MIN_ESTIMATES:
                self._apply(
                    THERMOCLINE_WIDTH,
                    sum(self.width_estimates) / len(self.width_estimates),
                )

    # ----- the cold shower button ---------------------------------------------------------

    def cold_shower(self, model: TankModel, now: datetime) -> list[ModelEvent]:
        """Learn the usable fraction from a shower that ran cold, and empty the model.

        The usable fraction becomes the model's cold fraction now, within its bounds (the user
        observed it, so the step limit of learned updates does not apply). The model is then set
        so that its tank water is 0. The interval that contains the reset is not a closure.
        The method observes the events of that reset itself, so the caller must not pass them
        to `observe` again.

        Args:
            model: The model.
            now: The time of the button press.

        Returns:
            The events of setting the model.
        """
        if USABLE_FRACTION not in self.locks:
            low, high = PARAMETER_BOUNDS[USABLE_FRACTION]
            fraction = min(max(model.cold_fraction, low), high)
            self.values[USABLE_FRACTION] = fraction
            self.sources[USABLE_FRACTION] = SOURCE_LEARNED
        model.set_options(self.options)
        usable = model.options.usable_fraction
        t_avg = model.t_ch - usable * (model.t_ch - model.t_cold)
        events = model.set_state(now, t_avg=t_avg)
        self.observe(model, events, now)
        return events

    # ----- persistence --------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the learned values and stored intervals as a JSON-compatible dict."""
        return {
            "values": dict(self.values),
            "sources": dict(self.sources),
            "closures": [c.as_dict() for c in self.closures],
            "quiet_estimates": list(self.quiet_estimates),
            "width_estimates": list(self.width_estimates),
            "pending": None if self._pending is None else self._pending.as_dict(),
            "unknown_start": self._unknown_start,
            "last_run_end": (
                None if self._last_run_end is None else self._last_run_end.isoformat()
            ),
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        """Restore the state saved by `to_dict`.

        Raises:
            ValueError: The data is malformed.
        """
        try:
            self.values = {n: float(v) for n, v in data["values"].items()}
            self.sources = {n: str(v) for n, v in data["sources"].items()}
            self.closures = [Closure.from_dict(c) for c in data["closures"]]
            self.quiet_estimates = [float(v) for v in data["quiet_estimates"]]
            self.width_estimates = [float(v) for v in data["width_estimates"]]
            pending = data.get("pending")
            self._pending = None if pending is None else _Pending.from_dict(pending)
            self._unknown_start = data.get("unknown_start")
            last_end = data.get("last_run_end")
            self._last_run_end = (
                None if last_end is None else datetime.fromisoformat(last_end)
            )
        except (KeyError, TypeError, AttributeError) as err:
            raise ValueError(f"Invalid calibration state: {err}") from err


__all__ = [
    "CLOSURE",
    "EXCLUDED",
    "PARAMETER_BOUNDS",
    "SENSOR_START",
    "Calibrator",
    "Closure",
    "bounded_step",
    "charge_error",
    "fit_closures",
    "heat_capacity",
    "true_start_average",
]
