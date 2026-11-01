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
    DEFAULT_RECLASSIFY_WINDOW,
    DEFAULT_SESSION_GAP,
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


@dataclass
class _Humidity:
    """The recent readings of one humidity sensor and whether it detects a shower."""

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
        self._long_active = False
        self._humidity: dict[str, _Humidity] = {}
        self._was_detected = False
        self._warned_units: set[str | None] = set()

    @property
    def detected(self) -> bool:
        """Return whether a shower or bath is detected, by humidity or the long-draw rule."""
        return self._long_active or any(h.active for h in self._humidity.values())

    @property
    def session_active(self) -> bool:
        """Return whether a draw session is open."""
        return self._last_increase is not None

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
        self, now: datetime, value: float | None, unit: str | None
    ) -> Classification | None:
        """Process a water meter reading.

        Args:
            now: Time of the reading.
            value: The meter reading in `unit`, None when unavailable or non-numeric.
            unit: The meter unit: m3, L, gal or ft3.

        Returns:
            The classified draw, or None when the reading drew no water.
        """
        self._expire_session(now)
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
        long_minutes = self.options.long_draw_minutes
        if (
            long_minutes > 0
            and not self._long_active
            and now - self._session_start >= timedelta(minutes=long_minutes)
        ):
            self._long_active = True
        reclassified = self._edge(now)
        mixed = self.detected
        if not mixed:
            self._others.append((now, delta))
            self._prune_others(now)
        return Classification(litres=delta, mixed=mixed, reclassified=reclassified)

    def on_humidity(self, now: datetime, sensor_id: str, value: float | None) -> float:
        """Process a humidity reading.

        Args:
            now: Time of the reading.
            sensor_id: Which sensor read it. Every sensor has its own window.
            value: Relative humidity in percent, None when unavailable.

        Returns:
            Litres to reclassify from other draws to mixed draws, 0 when detection did not
            start with this reading.
        """
        self._expire_session(now)
        if _finite(value):
            humidity = self._humidity.setdefault(sensor_id, _Humidity())
            humidity.readings.append((now, float(value)))
        return self.update(now)

    def update(self, now: datetime) -> float:
        """Advance time: end an old session, slide the humidity windows.

        Args:
            now: The current time.

        Returns:
            Litres to reclassify, as for `on_humidity`.
        """
        self._expire_session(now)
        for humidity in self._humidity.values():
            self._evaluate_humidity(now, humidity)
        return self._edge(now)

    def _evaluate_humidity(self, now: datetime, humidity: _Humidity) -> None:
        """Slide one sensor's window and update whether it detects a shower."""
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

    def _edge(self, now: datetime) -> float:
        """Return the litres to reclassify when detection has just started."""
        detected = self.detected
        rising = detected and not self._was_detected
        self._was_detected = detected
        if not rising:
            return 0.0
        start = now - timedelta(minutes=self.options.reclassify_window)
        litres = sum(amount for time, amount in self._others if time >= start)
        self._others.clear()
        return litres

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
            self._session_start = None
            self._last_increase = None
            self._others.clear()
            self._long_active = False
            self._was_detected = self.detected

    def to_dict(self) -> dict[str, Any]:
        """Return the state as a JSON-compatible dict."""
        return {
            "last_litres": self._last_litres,
            "session_start": _iso(self._session_start),
            "last_increase": _iso(self._last_increase),
            "others": [[time.isoformat(), amount] for time, amount in self._others],
            "long_active": self._long_active,
            "was_detected": self._was_detected,
            "humidity": {
                sensor_id: {
                    "readings": [[t.isoformat(), v] for t, v in humidity.readings],
                    "active": humidity.active,
                }
                for sensor_id, humidity in self._humidity.items()
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore the state from `to_dict`.

        Args:
            data: A dict produced by `to_dict`.

        Raises:
            ValueError: The data is malformed.
        """
        try:
            self._last_litres = data["last_litres"]
            self._session_start = _from_iso(data["session_start"])
            self._last_increase = _from_iso(data["last_increase"])
            self._others = [(datetime.fromisoformat(t), a) for t, a in data["others"]]
            self._long_active = bool(data["long_active"])
            self._was_detected = bool(data["was_detected"])
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
