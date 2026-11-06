"""The runtime of one tank: the model, the calibrator and their wiring to Home Assistant.

All the maths is in the pure modules (`model.py`, `calibration.py`, `setup_fit.py`). This module
turns state changes into model inputs and the model's events into calibration, persistence and
entity updates:

    source state change -> `TankEstimator._handle_state` -> `TankModel.on_*`
    5-minute interval   -> `TankEstimator._handle_tick`  -> `TankModel.tick`
    shower end timer    -> `TankEstimator._handle_shower_end` -> `TankModel.tick`
        -> `Calibrator.observe` (learns; changed options go back to `TankModel.set_options`)
        -> a delayed `Store` save, requested after every input and written once a minute at most
        -> a dispatcher signal that the entities listen to

The time of a reading is the state's `last_updated`: the moment the new reading was produced.
`last_changed` only moves when the value does, so a sensor that republishes an unchanged value
with new attributes would look older than it is.
"""

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import partial
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .calibration import (
    PARAMETER_BOUNDS,
    SHOWER_FLOW,
    USABLE_FRACTION,
    Calibrator,
    PressResult,
)
from .const import (
    CONF_AMBIENT_SENSOR,
    CONF_COLD_SENSOR,
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_HISTORY_DAYS,
    CONF_HUMIDITY_SENSORS,
    CONF_LOCKS,
    CONF_OUTSIDE_HEAT,
    CONF_POWER_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_THERMOCLINE_WIDTH,
    CONF_VOLUME,
    CONF_WATER_METER,
    DEFAULT_HISTORY_DAYS,
    DIAGNOSTIC_EVENTS,
    DOMAIN,
    FALLBACK_TEMPERATURE,
    SHOWER_HISTORY,
    SIGNAL_UPDATE,
    STORAGE_SAVE_DELAY,
    TICK_MINUTES,
)
from .history import async_read_history
from .model import EventKind, ModelEvent, ModelOptions, Sources, TankModel
from .readings import convert_reading
from .setup_fit import (
    AMBIENT_TEMPERATURE,
    BATHROOM_HUMIDITY,
    COLD_WATER_TEMPERATURE,
    DHW_ENERGY,
    DHW_HEATING,
    DHW_POWER,
    FLOW_TEMPERATURE,
    RETURN_TEMPERATURE,
    TANK_TEMPERATURE,
    WATER_METER,
    SetupFit,
    setup_fit,
)

_LOGGER = logging.getLogger(__name__)

type TankConfigEntry = ConfigEntry[TankEstimator]

# The tuning values of `ModelOptions` that the options form holds in the model's own units.
_TUNING_FIELDS = tuple(
    name
    for name in ModelOptions.__dataclass_fields__
    if name
    not in {
        "volume",
        "sensor_height",
        "thermocline_width",
        "shower_flow_range",
        "outside_heat",
    }
)
# The parameters the user can lock (the learned ones).
LOCKABLE = tuple(PARAMETER_BOUNDS)
__all__ = [
    "LOCKABLE",
    "TankConfig",
    "TankConfigEntry",
    "TankEstimator",
]

_UNAVAILABLE = {STATE_UNAVAILABLE, STATE_UNKNOWN}
# The roles whose last reading is a baseline, and the model source that forgets it.
_BASELINES = {WATER_METER: "water_meter", DHW_ENERGY: "energy_counter"}


class _Tolerant(dict[str, Any]):
    """Format values that leave an unknown placeholder as it is, so a text cannot break a press."""

    def __missing__(self, key: str) -> str:
        """Return the placeholder unchanged."""
        return "{" + key + "}"


@dataclass(frozen=True)
class TankConfig:
    """The configuration of one tank, read from the entry options.

    Attributes:
        options: The tuning values for the model, fractions as the model holds them.
        sources: Which sources are configured.
        routes: For each source entity, the roles it plays (the roles of `setup_fit`).
        locks: The locked learned parameters.
        history_days: The days of recorder history for the setup fit.
    """

    options: ModelOptions
    sources: Sources
    routes: Mapping[str, tuple[str, ...]]
    locks: frozenset[str]
    history_days: int

    @classmethod
    def from_options(cls, data: Mapping[str, Any]) -> TankConfig:
        """Create the configuration from the options of an entry."""
        values: dict[str, Any] = {
            name: float(data[name]) for name in _TUNING_FIELDS if name in data
        }
        if CONF_SENSOR_HEIGHT in data:
            values["sensor_height"] = float(data[CONF_SENSOR_HEIGHT]) / 100
        if CONF_THERMOCLINE_WIDTH in data:
            values["thermocline_width"] = float(data[CONF_THERMOCLINE_WIDTH]) / 100
        for name in ("cold_coldest_day",):
            if name in values:
                values[name] = int(values[name])
        if CONF_OUTSIDE_HEAT in data:
            values["outside_heat"] = bool(data[CONF_OUTSIDE_HEAT])
        options = ModelOptions(volume=float(data[CONF_VOLUME]), **values)

        humidity = tuple(data.get(CONF_HUMIDITY_SENSORS) or ())
        sources = Sources(
            energy_counter=bool(data.get(CONF_ENERGY_COUNTER)),
            power=bool(data.get(CONF_POWER_SENSOR)),
            heating_binary=bool(data.get(CONF_HEATING_ACTIVE)),
            flow_return=bool(
                data.get(CONF_FLOW_SENSOR) and data.get(CONF_RETURN_SENSOR)
            ),
            cold_sensor=bool(data.get(CONF_COLD_SENSOR)),
            ambient_sensor=bool(data.get(CONF_AMBIENT_SENSOR)),
            humidity_sensors=humidity,
        )
        pairs: list[tuple[str, str]] = [
            (data[CONF_TANK_SENSOR], TANK_TEMPERATURE),
            (data[CONF_WATER_METER], WATER_METER),
        ]
        optional = (
            (CONF_ENERGY_COUNTER, DHW_ENERGY),
            (CONF_POWER_SENSOR, DHW_POWER),
            (CONF_HEATING_ACTIVE, DHW_HEATING),
            (CONF_COLD_SENSOR, COLD_WATER_TEMPERATURE),
            (CONF_AMBIENT_SENSOR, AMBIENT_TEMPERATURE),
        )
        pairs += [(data[key], role) for key, role in optional if data.get(key)]
        if sources.flow_return:
            pairs += [
                (data[CONF_FLOW_SENSOR], FLOW_TEMPERATURE),
                (data[CONF_RETURN_SENSOR], RETURN_TEMPERATURE),
            ]
        pairs += [(entity_id, BATHROOM_HUMIDITY) for entity_id in humidity]
        routes: dict[str, tuple[str, ...]] = {}
        for entity_id, role in pairs:
            routes[entity_id] = (*routes.get(entity_id, ()), role)
        return cls(
            options=options,
            sources=sources,
            routes=routes,
            locks=frozenset(data.get(CONF_LOCKS) or ()) & set(LOCKABLE),
            history_days=int(data.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)),
        )

    @property
    def measures_heat(self) -> bool:
        """Return whether an energy counter or power sensor is configured."""
        return self.sources.energy_counter or self.sources.power


class TankEstimator:
    """One tank: the model, the calibrator, the listeners and the persistence."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config: TankConfig,
        store: Store[dict[str, Any]],
        stored: Mapping[str, Any] | None,
    ) -> None:
        """Create the estimator. Call `async_start` once the entities are added.

        Args:
            hass: Home Assistant.
            entry: The config entry.
            config: The configuration read from the entry options.
            store: The calibration store of the entry.
            stored: What the store held (None the first time).
        """
        self.hass = hass
        self.entry = entry
        self.config = config
        self.signal = SIGNAL_UPDATE.format(entry.entry_id)
        self._store = store
        self._unsubscribe: list[Any] = []
        # The one-shot timer at the model's next shower end, and the time it is set for.
        self._shower_timer: CALLBACK_TYPE | None = None
        self._shower_timer_at: datetime | None = None
        self._flow: float | None = None
        self._return: float | None = None
        self._fit_done = False
        # The ambient sensor entity the calibration was fitted with (None for none). A fit
        # against another one is due, because the loss coefficient depends on the ambient.
        self._ambient_fitted: str | None = None
        self.model_restored = False
        self._stopped = False
        # True once the current states of the sources have been fed to the model.
        self.fed = False
        self._save_pending = False
        self._fit_lock = asyncio.Lock()
        # Counts the button presses and manual resets, so a fit that was running while one
        # happened can keep its effect.
        self._manual = 0

        stored_locks: Iterable[str] = ()
        calibration: Mapping[str, Any] | None = None
        stored_model: Mapping[str, Any] | None = None
        stored_entities: Mapping[str, str] = {}
        if stored is not None:
            stored_model = stored.get("model")
            stored_entities = stored.get("entities", {})
            stored_locks = stored.get("locks", ())
            calibration = stored.get("calibrator")
            self._fit_done = bool(stored.get("fit_done", False))
            self._ambient_fitted = stored.get("ambient_fit")
        self.calibrator = Calibrator(
            config.options,
            locks=frozenset(stored_locks),
            measures_heat=config.measures_heat,
        )
        if calibration is not None:
            try:
                self.calibrator.restore(calibration)
            except ValueError:
                _LOGGER.warning("Discarding the stored calibration of %s", entry.title)
                self.calibrator = Calibrator(
                    config.options, measures_heat=config.measures_heat
                )
                self._fit_done = False
        # Removing a lock discards the value learned before it; the options may have changed.
        self.calibrator.set_base(config.options, config.locks)
        self.model = self._restored_model(stored_model) or TankModel(
            self.calibrator.options,
            config.sources,
            dt_util.utcnow(),
            self._first_temperature(),
        )
        if not self.model_restored:
            # A fresh model (T_avg from the sensor) cannot take back a drop D of the old one.
            self.calibrator.undo_record = None
        else:
            # A replaced counter or meter entity starts a new baseline.
            current = self._baseline_entities()
            for role, source in _BASELINES.items():
                if role in stored_entities and stored_entities[role] != current.get(
                    role
                ):
                    self.model.forget_reading(source)

    # ----- start and stop -----------------------------------------------------------------

    def _first_temperature(self) -> float:
        """Return the tank sensor's reading in C, 50 C when it is unavailable."""
        for entity_id, roles in self.config.routes.items():
            if TANK_TEMPERATURE in roles and (state := self.hass.states.get(entity_id)):
                value = convert_reading(
                    TANK_TEMPERATURE,
                    state.state,
                    state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
                )
                if value is not None:
                    return value
        return FALLBACK_TEMPERATURE

    def _restored_model(self, data: Mapping[str, Any] | None) -> TankModel | None:
        """Return the model saved in the store, None when there is none or it is malformed."""
        if data is None:
            return None
        try:
            model = TankModel.from_dict(
                self.calibrator.options, self.config.sources, dict(data)
            )
        except ValueError as err:
            _LOGGER.warning(
                "Ignoring the stored model of %s: %s", self.entry.title, err
            )
            return None
        self.model_restored = True
        return model

    def _baseline_entities(self) -> dict[str, str]:
        """Return the entity of each role that keeps a baseline reading."""
        return {
            role: entity_id
            for entity_id, roles in self.config.routes.items()
            for role in roles
            if role in _BASELINES
        }

    def _ambient_entity(self) -> str | None:
        """Return the configured ambient sensor entity, None when there is none."""
        return next(
            (
                entity_id
                for entity_id, roles in self.config.routes.items()
                if AMBIENT_TEMPERATURE in roles
            ),
            None,
        )

    @callback
    def async_start(self) -> None:
        """Feed the current states to the model, listen to the sources and start the interval."""
        now = dt_util.utcnow()
        events: list[ModelEvent] = []
        for entity_id in self.config.routes:
            events += self._feed(entity_id, self.hass.states.get(entity_id), now)
        self.fed = True
        self._finish(events, now)
        self._unsubscribe.append(
            async_track_state_change_event(
                self.hass, list(self.config.routes), self._handle_state
            )
        )
        self._unsubscribe.append(
            async_track_time_interval(
                self.hass,
                self._handle_tick,
                timedelta(minutes=TICK_MINUTES),
                name=f"{DOMAIN} tick",
            )
        )
        if not self._fit_done or self._ambient_fitted != self._ambient_entity():
            self.entry.async_create_background_task(
                self.hass, self.async_setup_fit(), f"{DOMAIN} setup fit"
            )

    async def async_stop(self) -> None:
        """Stop listening and save the model and the calibration."""
        self._stopped = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        self._cancel_shower_timer()
        self._save_pending = False
        await self._store.async_save(self.payload())

    # ----- inputs -------------------------------------------------------------------------

    @callback
    def _handle_state(self, event: Event[EventStateChangedData]) -> None:
        """Pass a source's new state to the model."""
        state = event.data["new_state"]
        now = state.last_updated if state is not None else dt_util.utcnow()
        self._finish(self._feed(event.data["entity_id"], state, now), now)

    @callback
    def _handle_tick(self, now: datetime) -> None:
        """Advance the model: loss, run timeout, detection windows and sensor bounds."""
        self._finish(self.model.tick(now), now)

    @callback
    def _handle_shower_end(self, now: datetime) -> None:
        """Run the tick path when the shower is due to end or a draw session has expired."""
        if self._stopped:
            return
        self._shower_timer = None
        self._shower_timer_at = None
        self._finish(self.model.tick(now), now)

    @property
    def shower_timer_at(self) -> datetime | None:
        """Return when the shower end timer is set for, None when none is pending."""
        return self._shower_timer_at

    @callback
    def _cancel_shower_timer(self) -> None:
        """Cancel the shower end timer, if one is pending."""
        if self._shower_timer is not None:
            self._shower_timer()
        self._shower_timer = None
        self._shower_timer_at = None

    @callback
    def _schedule_shower_end(self) -> None:
        """Point the one-shot timer at the model's next wake-up, or cancel it when there is none."""
        deadline = None if self._stopped else self.model.next_wake_up
        if deadline == self._shower_timer_at and (
            deadline is None or self._shower_timer is not None
        ):
            return
        self._cancel_shower_timer()
        if deadline is not None:
            self._shower_timer_at = deadline
            self._shower_timer = async_track_point_in_utc_time(
                self.hass,
                self._handle_shower_end,
                deadline,
            )

    def _feed(
        self, entity_id: str, state: State | None, now: datetime
    ) -> list[ModelEvent]:
        """Give a source's state to the model, as every role the source plays."""
        events: list[ModelEvent] = []
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        text = STATE_UNAVAILABLE if state is None else state.state
        for role in self.config.routes.get(entity_id, ()):
            value = convert_reading(role, text, unit)
            model = self.model
            match role:
                case "tank_temperature":
                    events += model.on_tank_sensor(now, value)
                case "water_meter":
                    events += model.on_water_meter(now, value, unit or "")
                case "dhw_energy":
                    events += model.on_energy(now, value)
                case "dhw_power":
                    events += model.on_power(now, value)
                case "dhw_heating":
                    active = (
                        True
                        if text == STATE_ON
                        else False
                        if text == STATE_OFF
                        else None
                    )
                    events += model.on_heating(now, active)
                case "flow_temperature" | "return_temperature":
                    if role == FLOW_TEMPERATURE:
                        self._flow = value
                    else:
                        self._return = value
                    events += model.on_flow_return(now, self._flow, self._return)
                case "bathroom_humidity":
                    events += model.on_humidity(now, entity_id, value)
                case "cold_water_temperature":
                    events += model.on_cold_water_sensor(now, value)
                case "ambient_temperature":
                    events += model.on_ambient_sensor(now, value)
        return events

    @callback
    def _finish(self, events: list[ModelEvent], now: datetime) -> None:
        """Learn from the events, save soon and tell the entities."""
        before = self.calibrator.options
        if self.calibrator.observe(self.model, events, now):
            self.model.set_options(self.calibrator.options)
            self._log_calibration(now, "learning", before)
        self._schedule_shower_end()
        self.save_soon()
        async_dispatcher_send(self.hass, self.signal)

    def _log_calibration(
        self, now: datetime, trigger: str, before: ModelOptions
    ) -> None:
        """Log a calibration event with the old and new values and the source of each."""
        after = self.calibrator.options
        changed = {
            name: {
                "old": getattr(before, name),
                "new": getattr(after, name),
                "source": self.calibrator.source_of(name),
            }
            for name in PARAMETER_BOUNDS
            if getattr(before, name) != getattr(after, name)
        }
        if changed:
            self.model.log_event(
                now, EventKind.CALIBRATION, {"trigger": trigger, "parameters": changed}
            )

    # ----- persistence --------------------------------------------------------------------

    def payload(self) -> dict[str, Any]:
        """Return what the store keeps: the model, the calibration, the locks and the fit flag."""
        return {
            "model": self.model.to_dict(),
            "entities": self._baseline_entities(),
            "calibrator": self.calibrator.to_dict(),
            "locks": sorted(self.calibrator.locks),
            "fit_done": self._fit_done,
            "ambient_fit": self._ambient_fitted,
        }

    def _payload_for_save(self) -> dict[str, Any]:
        """Return the payload when the store writes, which ends the pending delayed save."""
        self._save_pending = False
        return self.payload()

    @callback
    def save_soon(self) -> None:
        """Save the model and the calibration after a short delay.

        `Store.async_delay_save` moves a pending write to the latest request plus the delay, so
        continuous inputs would postpone it forever. A request is made only when none is
        pending: the first input after a write starts the delay, and the write happens one delay
        later whatever arrives meanwhile. The store is written at most once per delay.
        """
        if self._save_pending:
            return
        self._save_pending = True
        self._store.async_delay_save(self._payload_for_save, STORAGE_SAVE_DELAY)

    # ----- actions ------------------------------------------------------------------------

    @callback
    def set_state(self, t_avg: float | None, t_ch: float | None) -> None:
        """Set the temperatures by hand.

        Raises:
            ValueError: Neither is given and the tank sensor is unavailable.
        """
        now = dt_util.utcnow()
        # Process anything due first, so that a failed call leaves nothing unobserved.
        self._finish(self.model.tick(now), now)
        events = self.model.set_state(now, t_avg, t_ch)
        self._manual += 1
        self._finish(events, now)

    async def async_hot_water_ran_out(self) -> None:
        """Handle a press of "Hot water ran out": learn from it, or explain why not."""
        now = dt_util.utcnow()
        self._finish(self.model.tick(now), now)
        before_options = self.calibrator.options
        before = (self.model.t_avg, self.model.t_ch)
        result = self.calibrator.hot_water_ran_out(self.model, now)
        if result.accepted:
            self._manual += 1
            change: dict[str, Any] = {"result": "accepted", **result.values}
        else:
            change = {
                "result": "rejected",
                "reason": result.reason,
                **result.values,
            }
        self.model.log_event(now, EventKind.HOT_WATER_RAN_OUT, change, before)
        if result.accepted:
            self._log_calibration(now, "hot_water_ran_out", before_options)
            persistent_notification.async_dismiss(self.hass, self._press_notification)
        else:
            await self._notify_rejected_press(result)
        self.save_soon()
        async_dispatcher_send(self.hass, self.signal)

    def undo_available(self) -> bool:
        """Return whether "Undo hot water ran out" would do something now."""
        return self.calibrator.undo_available(self.model, dt_util.utcnow())

    async def async_undo_hot_water_ran_out(self) -> None:
        """Handle a press of "Undo hot water ran out".

        Raises:
            ServiceValidationError: There is nothing to undo (a race with the button's
                availability).
        """
        now = dt_util.utcnow()
        self._finish(self.model.tick(now), now)
        before_options = self.calibrator.options
        before = (self.model.t_avg, self.model.t_ch)
        result = self.calibrator.undo(self.model, now)
        if result is None:
            self.save_soon()
            async_dispatcher_send(self.hass, self.signal)
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_undo"
            )
        # A fit that was running keeps the undone usable fraction and the cleared record.
        self._manual += 1
        self.model.log_event(
            now,
            EventKind.HOT_WATER_RAN_OUT,
            {
                "result": "undone",
                "usable_fraction": result.usable_fraction,
                "rise": result.rise,
                "after_reset": result.after_reset,
            },
            before,
        )
        self._log_calibration(now, "undo_hot_water_ran_out", before_options)
        self.save_soon()
        async_dispatcher_send(self.hass, self.signal)

    async def async_set_shower_flow(self, value: float) -> None:
        """Set the shower flow by hand: it is kept and locked, also in the options.

        The lock is written to the entry options, which the options flow shows and which win
        over the store when the entry loads. The entry does not reload for it.
        """
        now = dt_util.utcnow()
        old = self.calibrator.value_of(SHOWER_FLOW)
        new = self.calibrator.set_shower_flow(value)
        self.model.set_options(self.calibrator.options)
        locks = {*(self.entry.options.get(CONF_LOCKS) or ()), SHOWER_FLOW}
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_LOCKS: sorted(locks)}
        )
        self.config = replace(self.config, locks=self.config.locks | {SHOWER_FLOW})
        self.model.log_event(
            now, EventKind.SHOWER_FLOW, {"result": "set", "old": old, "new": new}
        )
        self.save_soon()
        async_dispatcher_send(self.hass, self.signal)

    async def async_set_shower_flow_locked(self, locked: bool) -> None:
        """Lock the shower flow in use, or unlock it back to the median of the history.

        It is the lock of the number and of the options flow: the calibrator's locks and the
        entry options' lock list, written without a reload. Locking holds the flow in use at
        that moment. Unlocking does what removing the lock in the options does.
        """
        calibrator = self.calibrator
        if (SHOWER_FLOW in calibrator.locks) == locked:
            return
        now = dt_util.utcnow()
        if locked:
            calibrator.set_locks(calibrator.locks | {SHOWER_FLOW})
        else:
            calibrator.set_locks(calibrator.locks - {SHOWER_FLOW})
        self.model.set_options(calibrator.options)
        locks = set(self.entry.options.get(CONF_LOCKS) or ())
        locks = locks | {SHOWER_FLOW} if locked else locks - {SHOWER_FLOW}
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_LOCKS: sorted(locks)}
        )
        locks = self.config.locks
        self.config = replace(
            self.config,
            locks=locks | {SHOWER_FLOW} if locked else locks - {SHOWER_FLOW},
        )
        self.model.log_event(
            now,
            EventKind.SHOWER_FLOW,
            {
                "result": "locked" if locked else "unlocked",
                "flow": calibrator.value_of(SHOWER_FLOW),
            },
        )
        self.save_soon()
        async_dispatcher_send(self.hass, self.signal)

    @property
    def _press_notification(self) -> str:
        """Return the notification ID of this tank's rejected press (one at a time)."""
        return f"{DOMAIN}_{self.entry.entry_id}_hot_water_ran_out"

    async def _notify_rejected_press(self, result: PressResult) -> None:
        """Show why a press was ignored, in the language of Home Assistant."""
        key = f"press_ignored_{result.reason}"
        texts = await async_get_translations(
            self.hass, self.hass.config.language, "exceptions", [DOMAIN]
        )
        template = texts.get(f"component.{DOMAIN}.exceptions.{key}.message", key)
        values = {
            name: f"{value:.1f}" if isinstance(value, float) else value
            for name, value in result.values.items()
        }
        persistent_notification.async_create(
            self.hass,
            template.format_map(_Tolerant(values)),
            title=self.entry.title,
            notification_id=self._press_notification,
        )

    # ----- the setup fit ------------------------------------------------------------------

    def _snapshot(self) -> Calibrator:
        """Return a copy of the calibrator for the executor: the live one is never shared."""
        copy = Calibrator(
            self.config.options,
            locks=self.calibrator.locks,
            measures_heat=self.config.measures_heat,
        )
        copy.restore(self.calibrator.to_dict())
        copy.shower_added = self.calibrator.shower_added
        return copy

    async def async_setup_fit(self, days: int | None = None) -> SetupFit | None:
        """Replay the recorder history through the model and fit the parameters.

        The recorder is read through its own executor and the replay runs in the default
        executor, so the event loop is never blocked. Fits run one at a time.

        Args:
            days: The days of history, by default the configured number.

        Returns:
            The fit, or None when the recorder is not available or holds no history.
        """
        if "recorder" not in self.hass.config.components:
            _LOGGER.info("The recorder is not set up, skipping the setup fit")
            return None
        async with self._fit_lock:
            if self._stopped:
                return None
            # What the fit starts from is taken now: a press or reset from here on is kept.
            manual = self._manual
            previous = self._snapshot()
            end = dt_util.utcnow()
            start = end - timedelta(days=days or self.config.history_days)
            history = await async_read_history(self.hass, self.config, start, end)
            if self._stopped:
                return None
            if not any(series.states for series in history.series):
                _LOGGER.info("No history to fit for %s", self.entry.title)
                self._fit_done = True
                self._ambient_fitted = self._ambient_entity()
                self.save_soon()
                return None
            fit = await self.hass.async_add_executor_job(
                partial(
                    setup_fit,
                    history,
                    self.config.options,
                    locks=self.config.locks,
                    sources=self.config.sources,
                    previous=previous,
                )
            )
            if self._stopped:
                return None
            self._apply_fit(fit, manual_at_start=manual, previous=previous)
            return fit

    @callback
    def _apply_fit(
        self, fit: SetupFit, *, manual_at_start: int, previous: Calibrator
    ) -> None:
        """Replace the calibration with the fit, keeping what the user did while it ran."""
        now = dt_util.utcnow()
        before = self.calibrator.options
        live = self.calibrator
        calibrator = fit.calibrator
        if self._manual != manual_at_start:
            # A button press or a manual reset happened during the fit. The replay could
            # not know: keep the pressed usable fraction and the excluded interval.
            state = calibrator.to_dict()
            state["unknown_start"] = live.to_dict()["unknown_start"]
            if (
                live.values.get(USABLE_FRACTION) != previous.values.get(USABLE_FRACTION)
                and USABLE_FRACTION not in calibrator.locks
            ):
                # Pressed or undone during the fit: the live value, or none, stays.
                for key, source in (("values", live.values), ("sources", live.sources)):
                    if USABLE_FRACTION in source:
                        state[key][USABLE_FRACTION] = source[USABLE_FRACTION]
                    else:
                        state[key].pop(USABLE_FRACTION, None)
            calibrator.restore(state)
        # A shower learned during the fit is not in the replay: its sample is added to the
        # replay's history. A flow set by hand during the fit stays locked, and a lock removed during it stays removed.
        added = live.shower_added - previous.shower_added
        if added > 0:
            calibrator.shower_flows.extend(live.shower_flows[-added:])
            del calibrator.shower_flows[:-SHOWER_HISTORY]
        if SHOWER_FLOW in live.locks and SHOWER_FLOW in live.values:
            calibrator.values[SHOWER_FLOW] = live.values[SHOWER_FLOW]
            calibrator.locks = calibrator.locks | {SHOWER_FLOW}
        elif SHOWER_FLOW not in live.locks and SHOWER_FLOW in calibrator.locks:
            # The lock was removed during the fit: it stays removed, and the held value goes.
            calibrator.set_locks(calibrator.locks - {SHOWER_FLOW})
        # The record of the last press is the live one: a press or an undo during the fit,
        # or the first reset it has seen since, is not in the replay's copy.
        calibrator.undo_record = live.undo_record
        self.calibrator = calibrator
        self._fit_done = True
        self._ambient_fitted = self._ambient_entity()
        self.model.set_options(calibrator.options)
        self._log_calibration(now, "setup_fit", before)
        self.save_soon()
        async_dispatcher_send(self.hass, self.signal)

    # ----- diagnostics --------------------------------------------------------------------

    def source_availability(self) -> dict[str, bool]:
        """Return whether each configured source currently has a usable state."""
        result: dict[str, bool] = {}
        for entity_id in self.config.routes:
            state = self.hass.states.get(entity_id)
            result[entity_id] = state is not None and state.state not in _UNAVAILABLE
        return result

    def recent_events(self) -> list[dict[str, Any]]:
        """Return the most recent model events, oldest first."""
        return [event.as_dict() for event in self.model.events[-DIAGNOSTIC_EVENTS:]]
