"""Draw classification: which litres of a whole-house meter are shower water.

Pure Python: standard library only, no Home Assistant imports and no I/O. It lives beside
`model.py` rather than inside it because it holds its own state (meter, session, humidity
windows), has its own spec and tests, and `model.py` only needs its three results: litres of
mixed draw, litres of other draw and litres to reclassify.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
from typing import Any

from .const import (
    DEFAULT_HUMIDITY_RISE,
    DEFAULT_HUMIDITY_WINDOW,
    DEFAULT_LONG_DRAW_MINUTES,
    DEFAULT_MAX_DRAW,
    DEFAULT_NEXT_SHOWER_MINUTES,
    DEFAULT_RECLASSIFY_WINDOW,
    DEFAULT_SESSION_GAP,
    DEFAULT_SHOWER_END_MINUTES,
    ROLLING_FLOW_MIN_SECONDS,
    ROLLING_FLOW_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# Litres per meter unit, keyed by the lower-cased unit text.
_LITRES_PER_UNIT: dict[str, float] = {
    "l": 1.0,
    "m3": 1000.0,
    "m³": 1000.0,
    "gal": 3.785411784,
    "ft3": 28.316846592,
    "ft³": 28.316846592,
}


def litres_from_meter(value: float, unit: str | None) -> float | None:
    """Convert a meter reading to litres.

    Args:
        value: The meter reading.
        unit: The unit of the reading: m3, L, gal or ft3.

    Returns:
        The reading in litres, or None for an unknown unit (including None).
    """
    if unit is None:
        return None
    factor = _LITRES_PER_UNIT.get(unit.strip().lower())
    return None if factor is None else value * factor


@dataclass(frozen=True, kw_only=True)
class ClassifierOptions:
    """The tuning values of the draw classification."""

    humidity_rise: float = DEFAULT_HUMIDITY_RISE  # percentage points
    humidity_window: float = DEFAULT_HUMIDITY_WINDOW  # minutes
    long_draw_minutes: float = DEFAULT_LONG_DRAW_MINUTES  # 0 is off
    reclassify_window: float = DEFAULT_RECLASSIFY_WINDOW  # minutes
    session_gap: float = DEFAULT_SESSION_GAP  # seconds
    max_draw: float = DEFAULT_MAX_DRAW  # litres per reading
    shower_end_minutes: float = DEFAULT_SHOWER_END_MINUTES  # minutes
    next_shower_minutes: float = DEFAULT_NEXT_SHOWER_MINUTES  # minutes
    # Whether a humidity sensor is configured (from the entry's sources, not from readings):
    # the long-draw rule starts a shower only without one.
    humidity_configured: bool = False


@dataclass(frozen=True)
class Classification:
    """The result of one meter reading that drew water.

    Attributes:
        litres: Litres drawn since the previous valid reading.
        mixed: True when the litres are a mixed draw, False for another draw.
        reclassified: Litres that earlier counted as other draws and are mixed draws now,
            because a shower was detected with this reading. The caller corrects the model
            by the energy difference.
    """

    litres: float
    mixed: bool
    reclassified: float = 0.0


@dataclass(frozen=True)
class ShowerReport:
    """A detected shower that has ended.

    Attributes:
        litres: The mixed litres drawn within its minutes of flow: those reclassified at
            detection included, the first increase of each session left out (it was drawn
            before the session began).
        minutes: The minutes of flow: the summed duration of the shower's draw sessions, each
            from its first to its last increase, so a pause longer than the session gap does
            not count.
    """

    litres: float
    minutes: float


@dataclass
class _Shower:
    """The mixed draw of the shower in progress.

    Attributes:
        start: The time the shower started. None only for a shower restored without any
            time, which takes the time of the next call.
        litres: Mixed litres so far, without the first increase of each session.
        seconds: Seconds of flow so far.
        last: The time of the latest increase.
        recent: The latest increases as `(litres, seconds)`, where `seconds` is the time since
            the previous increase of the same session and 0 for the first of a session. Only
            the increases the rolling flow can reach are kept.
    """

    start: datetime | None = None
    litres: float = 0.0
    seconds: float = 0.0
    last: datetime | None = None
    recent: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class _Humidity:
    """The recent readings of one humidity sensor and whether it reads humid."""

    readings: list[tuple[datetime, float]] = field(default_factory=list)
    active: bool = False


def _finite(value: Any) -> bool:
    """Return whether a value is a real number (not None, bool, NaN or infinite)."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


class DrawClassifier:
    """Turns whole-house meter readings and humidity readings into classified draws."""

    def __init__(self, options: ClassifierOptions) -> None:
        """Create a classifier with no history."""
        self.options = options
        self._last_litres: float | None = None
        self._session_start: datetime | None = None
        self._last_increase: datetime | None = None
        # Litres of the current session that counted as other draws: (time, litres).
        self._others: list[tuple[datetime, float]] = []
        self._humidity: dict[str, _Humidity] = {}
        # Whether the bathroom counted as humid at the last evaluation: a shower starts on the
        # edge to humid, so a bathroom that is still humid after a shower starts none.
        self._was_humid = False
        # The end of a session that has ended and was not taken yet (see `take_session_end`).
        self._ended: datetime | None = None
        # The shower in progress, and one that has ended and was not taken yet.
        self._shower: _Shower | None = None
        self._shower_report: ShowerReport | None = None
        self._warned_units: set[str | None] = set()
        # Whether no humidity sensor reports, as of the last call (the model passes it with
        # every call; it is derived from the sensors' reports, so it is not saved).
        self._degraded = False

    @property
    def detected(self) -> bool:
        """Return whether a shower or bath is in progress (not whether the bathroom is humid)."""
        return self._shower is not None

    @property
    def humid(self) -> bool:
        """Return whether the bathroom counts as humid: a humidity sensor reads a rise.

        It is on from the rise above the window minimum until the humidity falls below that
        minimum plus half the rise. It starts a shower on its edge and, while on, lets a draw
        session of the next shower time start one; a shower in progress does not end by it.
        """
        return any(h.active for h in self._humidity.values())

    @property
    def shower_end(self) -> datetime | None:
        """Return when the shower in progress ends if no water is drawn, None without one.

        It is the later of the shower's last meter increase and its start, plus the shower
        end time.
        """
        shower = self._shower
        if shower is None:
            return None
        reference = self._reference(shower)
        if reference is None:
            return None
        return reference + timedelta(minutes=self.options.shower_end_minutes)

    @property
    def session_shower_time(self) -> datetime | None:
        """Return when the draw session in progress becomes a shower, None when it cannot.

        With no shower in progress and a session open, it is the session start plus the next
        shower time while the bathroom is humid or no humidity sensor reports (degraded), or
        plus the long-draw duration without a humidity sensor and with the rule on. It is the
        earliest moment: the shower starts at the first meter increase at or after it.
        Read-only; it changes nothing.
        """
        start = self._session_start
        if self._shower is not None or start is None:
            return None
        options = self.options
        if self.humid or self._degraded:
            return start + timedelta(minutes=options.next_shower_minutes)
        if options.long_draw_minutes > 0 and not options.humidity_configured:
            return start + timedelta(minutes=options.long_draw_minutes)
        return None

    @property
    def session_expiry(self) -> datetime | None:
        """Return the first moment the open draw session is noticed as ended, None without one.

        It is the last meter increase plus the session gap, plus one second: the session
        expires on a strict comparison, so a call at exactly the gap still sees it open.
        Read-only; it changes nothing.
        """
        if self._last_increase is None:
            return None
        # The margin makes a call at this time see the session as ended (`_expire_session`
        # compares with a strict `>`).
        return self._last_increase + timedelta(seconds=self.options.session_gap + 1)

    @property
    def session_active(self) -> bool:
        """Return whether a draw session is open."""
        return self._last_increase is not None

    def take_session_end(self) -> datetime | None:
        """Return the end of the draw session that ended since the last call, once.

        The end of a session is the time of its last increase. A session ends when the session
        gap has passed, which the classifier notices at its next call, so the caller asks after
        every call that advances time. When several sessions ended unnoticed, only the last one
        is reported.

        Returns:
            The end time of the session, None when no session ended.
        """
        ended, self._ended = self._ended, None
        return ended

    def take_shower_end(self) -> ShowerReport | None:
        """Return the shower that ended since the last call, once.

        A shower ends once no water has been drawn for the shower end time. The classifier
        notices at its next call, so the caller asks after every call. A shower without any
        draw reports nothing.

        Returns:
            The litres and minutes of flow of the shower, None when none ended.
        """
        report, self._shower_report = self._shower_report, None
        return report

    @property
    def rolling_flow(self) -> float | None:
        """Return the rolling flow of the shower in progress in L/min, None when there is none.

        It is the mixed litres over the last 2 minutes of flow divided by those minutes: the
        time between the increases of a session counts, a pause longer than the session gap
        does not. The litre of a session's first increase was drawn before the session, so it
        is not part of the window. There is none while no shower is in progress, or with less
        than 1 minute of flow in the shower.
        """
        shower = self._shower
        if shower is None or shower.seconds < ROLLING_FLOW_MIN_SECONDS:
            return None
        seconds = litres = 0.0
        for amount, duration in reversed(shower.recent):
            if duration <= 0:
                continue
            if seconds > 0 and seconds + duration > ROLLING_FLOW_SECONDS:
                break
            seconds += duration
            litres += amount
        return litres / seconds * 60 if seconds > 0 else None

    def clear_pending(self, until: datetime | None = None) -> None:
        """Forget the other-draw litres that could still be reclassified (after a charge).

        Args:
            until: Forget only litres drawn at or before this time (a charge as of an earlier
                run end leaves later litres reclassifiable). None forgets all.
        """
        if until is None:
            self._others.clear()
        else:
            self._others = [(t, amount) for t, amount in self._others if t > until]

    def forget_meter(self) -> None:
        """Forget the last meter reading: the next one is a new starting point."""
        self._last_litres = None

    def set_options(self, options: ClassifierOptions) -> None:
        """Use new tuning values and keep the state."""
        self.options = options

    def on_meter(
        self,
        now: datetime,
        value: float | None,
        unit: str | None,
        *,
        degraded: bool = False,
    ) -> Classification | None:
        """Process a water meter reading.

        Args:
            now: Time of the reading.
            value: The meter reading in `unit`, None when unavailable or non-numeric.
            unit: The meter unit: m3, L, gal or ft3.
            degraded: Whether humidity sensors are configured and none reports (all are
                unavailable or silent): a draw session of the next shower time then starts a
                shower, as in the humid bathroom.

        Returns:
            The classified draw, or None when the reading drew no water.
        """
        self._degraded = degraded
        self._advance(now)
        if not _finite(value):
            # The last valid reading stays the starting point, so a meter that was offline
            # for a while applies the change since that reading when it returns.
            return None
        litres_now = litres_from_meter(float(value), unit)
        if litres_now is None:
            if unit not in self._warned_units:
                self._warned_units.add(unit)
                _LOGGER.warning(
                    "Water meter unit %r is not a volume unit, readings ignored", unit
                )
            return None
        last = self._last_litres
        self._last_litres = litres_now
        if last is None:
            return None
        delta = round(litres_now - last, 6)
        if delta <= 0:
            # A decrease is a reset: no draw, and this reading is the new starting point.
            return None
        if delta > self.options.max_draw:
            _LOGGER.warning(
                "Water meter rose by %.1f L in one reading (maximum %.1f L), ignoring it",
                delta,
                self.options.max_draw,
            )
            return None

        if self._session_start is None:
            self._session_start = now
        self._last_increase = now
        reclassified = self._maybe_start(now, session=True)
        mixed = self.detected
        if mixed:
            self._shower_add(now, delta)
        else:
            self._others.append((now, delta))
            self._prune_others(now)
        return Classification(litres=delta, mixed=mixed, reclassified=reclassified)

    def on_humidity(
        self,
        now: datetime,
        sensor_id: str,
        value: float | None,
        *,
        degraded: bool = False,
    ) -> float:
        """Process a humidity reading.

        Args:
            now: Time of the reading.
            sensor_id: Which sensor read it. Every sensor has its own window.
            value: Relative humidity in percent, None when unavailable.
            degraded: As for `on_meter`, after this reading: a valid reading ends it.

        Returns:
            Litres to reclassify from other draws to mixed draws, 0 when detection did not
            start with this reading.
        """
        self._advance(now)
        if _finite(value):
            humidity = self._humidity.setdefault(sensor_id, _Humidity())
            humidity.readings.append((now, float(value)))
        return self.update(now, degraded=degraded)

    def update(self, now: datetime, *, degraded: bool = False) -> float:
        """Advance time: end an old session and a due shower, slide the humidity windows.

        Args:
            now: The current time.
            degraded: As for `on_meter`.

        Returns:
            Litres to reclassify, as for `on_humidity`.
        """
        self._degraded = degraded
        self._advance(now)
        for humidity in self._humidity.values():
            self._evaluate_humidity(now, humidity)
        return self._maybe_start(now, session=False)

    def _advance(self, now: datetime) -> None:
        """End the session and the shower that are due, before a reading is handled.

        A shower ends at its deadline whatever time the call comes, so a reading after the
        deadline is handled as one after the shower and the result does not depend on how
        often the caller calls.
        """
        self._expire_session(now)
        shower = self._shower
        if shower is None:
            return
        if shower.start is None:
            shower.start = now
        deadline = self.shower_end
        if deadline is not None and deadline <= now:
            self._end_shower()

    def _evaluate_humidity(self, now: datetime, humidity: _Humidity) -> None:
        """Slide one sensor's window and update whether it reads humid."""
        cutoff = now - timedelta(minutes=self.options.humidity_window)
        readings = humidity.readings
        # Keep the last reading before the cutoff: it is the value in effect at the window start.
        while len(readings) > 1 and readings[1][0] <= cutoff:
            readings.pop(0)
        if not readings:
            return
        minimum = min(value for _, value in readings)
        current = readings[-1][1]
        rise = self.options.humidity_rise
        if humidity.active:
            humidity.active = current >= minimum + rise / 2
        else:
            humidity.active = current - minimum >= rise

    def _maybe_start(self, now: datetime, *, session: bool) -> float:
        """Start a shower when a trigger holds and none is in progress.

        The triggers are the edge to humid, a draw session of the next shower time while the
        bathroom is humid or no humidity sensor reports (degraded), and, without a humidity
        sensor, a session of the long-draw duration.

        Args:
            now: The current time.
            session: Whether a draw increase just happened, so the session triggers apply.

        Returns:
            The litres of other draws that the shower takes over, 0 when none started.
        """
        humid = self.humid
        edge = humid and not self._was_humid
        self._was_humid = humid
        if self._shower is not None:
            return 0.0
        start = edge
        if not start and session and self._session_start is not None:
            lasted = now - self._session_start
            options = self.options
            if humid or self._degraded:
                start = lasted >= timedelta(minutes=options.next_shower_minutes)
            elif options.long_draw_minutes > 0 and not options.humidity_configured:
                start = lasted >= timedelta(minutes=options.long_draw_minutes)
        if not start:
            return 0.0
        window_start = now - timedelta(minutes=self.options.reclassify_window)
        reclassified = [
            (time, amount) for time, amount in self._others if time >= window_start
        ]
        self._others.clear()
        # The shower starts with the litres it takes over, in the order they were drawn.
        self._shower = _Shower(start=now)
        for time, amount in reclassified:
            self._shower_add(time, amount)
        return sum(amount for _, amount in reclassified)

    @staticmethod
    def _reference(shower: _Shower) -> datetime | None:
        """Return the time the shower end counts from: the later of its last increase and its start."""
        times = [t for t in (shower.start, shower.last) if t is not None]
        return max(times) if times else None

    def _shower_add(self, time: datetime, litres: float) -> None:
        """Add a mixed increase to the shower in progress (a new one when there is none)."""
        shower = self._shower
        if shower is None:
            shower = self._shower = _Shower()
        seconds = 0.0
        first = True
        if shower.last is not None:
            gap = (time - shower.last).total_seconds()
            if 0 <= gap <= self.options.session_gap:
                seconds = gap
                first = False
        if not first:
            shower.litres += litres
        shower.seconds += seconds
        shower.last = time
        shower.recent.append((litres, seconds))
        # Keep the increases back to the one that reaches past the rolling window.
        total = 0.0
        for index in range(len(shower.recent) - 1, -1, -1):
            total += shower.recent[index][1]
            if total > ROLLING_FLOW_SECONDS:
                del shower.recent[:index]
                break

    def _end_shower(self) -> None:
        """End the shower in progress and keep its report."""
        shower = self._shower
        if shower is None:
            return
        self._shower = None
        if shower.litres > 0:
            self._shower_report = ShowerReport(shower.litres, shower.seconds / 60)

    def _prune_others(self, now: datetime) -> None:
        """Drop other-draw litres that can no longer fall inside a reclassify window."""
        start = now - timedelta(minutes=self.options.reclassify_window)
        self._others = [
            (time, amount) for time, amount in self._others if time >= start
        ]

    def _expire_session(self, now: datetime) -> None:
        """End the session once the gap since its last increase has passed."""
        if self._last_increase is None:
            return
        if (now - self._last_increase).total_seconds() > self.options.session_gap:
            self._ended = self._last_increase
            self._session_start = None
            self._last_increase = None
            self._others.clear()

    def to_dict(self) -> dict[str, Any]:
        """Return the state as a JSON-compatible dict."""
        return {
            "last_litres": self._last_litres,
            "session_start": _iso(self._session_start),
            "last_increase": _iso(self._last_increase),
            "others": [[time.isoformat(), amount] for time, amount in self._others],
            # Keys the previous release reads: it restores them, so a rollback keeps the model.
            # `long_active` is always false, and `was_detected` holds the humid edge state.
            "long_active": False,
            "was_detected": self._was_humid,
            "shower": (
                None
                if self._shower is None
                else {
                    "start": _iso(self._shower.start),
                    "litres": self._shower.litres,
                    "seconds": self._shower.seconds,
                    "last": _iso(self._shower.last),
                    "recent": [list(item) for item in self._shower.recent],
                }
            ),
            "humidity": {
                sensor_id: {
                    "readings": [[t.isoformat(), v] for t, v in humidity.readings],
                    "active": humidity.active,
                }
                for sensor_id, humidity in self._humidity.items()
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore the state from `to_dict`, or from the previous release's.

        Args:
            data: A dict produced by `to_dict`. A shower without a start time takes its last
                increase, else the time of the next call.

        Raises:
            ValueError: The data is malformed.
        """
        try:
            self._last_litres = data["last_litres"]
            self._session_start = _from_iso(data["session_start"])
            self._last_increase = _from_iso(data["last_increase"])
            self._others = [(datetime.fromisoformat(t), a) for t, a in data["others"]]
            self._was_humid = bool(data["was_detected"])
            shower = data.get("shower")
            if shower is None:
                self._shower = None
            else:
                last = _from_iso(shower["last"])
                start = _from_iso(shower.get("start")) or last
                self._shower = _Shower(
                    start=start,
                    litres=float(shower["litres"]),
                    seconds=float(shower["seconds"]),
                    last=last,
                    recent=[(float(a), float(b)) for a, b in shower["recent"]],
                )
            self._humidity = {
                sensor_id: _Humidity(
                    readings=[
                        (datetime.fromisoformat(t), v) for t, v in item["readings"]
                    ],
                    active=bool(item["active"]),
                )
                for sensor_id, item in data["humidity"].items()
            }
        except (KeyError, TypeError, AttributeError) as err:
            raise ValueError(f"Invalid classifier state: {err}") from err


def _iso(value: datetime | None) -> str | None:
    """Return an ISO string for a datetime, or None."""
    return None if value is None else value.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    """Return the datetime of an ISO string, or None."""
    return None if value is None else datetime.fromisoformat(value)
