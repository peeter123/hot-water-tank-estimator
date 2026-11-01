"""Config flow and options flow of the Hot Water Tank Estimator integration.

The config flow has five steps (tank, water meter, heat input, shower detection, cold water). The
options flow shows the same fields again, with every tuning value, the locks and the history days.
Everything the user sets is stored in the entry options.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, override

import probatio

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .calibration import PARAMETER_BOUNDS
from .classification import litres_from_meter
from .const import (
    CONF_COLD_SENSOR,
    CONF_ENERGY_COUNTER,
    CONF_FLOW_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_HISTORY_DAYS,
    CONF_HUMIDITY_SENSORS,
    CONF_LOCKS,
    CONF_POWER_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_SENSOR_HEIGHT,
    CONF_TANK_SENSOR,
    CONF_THERMOCLINE_WIDTH,
    CONF_VOLUME,
    CONF_WATER_METER,
    DEFAULT_AMBIENT_TEMPERATURE,
    DEFAULT_COLD_AMPLITUDE,
    DEFAULT_COLD_COLDEST_DAY,
    DEFAULT_COLD_MEAN,
    DEFAULT_HISTORY_DAYS,
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
    DOMAIN,
    MAX_HISTORY_DAYS,
    MAX_SENSOR_HEIGHT,
    MAX_VOLUME,
    MIN_HISTORY_DAYS,
    MIN_SENSOR_HEIGHT,
    MIN_VOLUME,
)


@dataclass(frozen=True)
class Tuning:
    """One numeric tuning value of the options form."""

    key: str
    default: float
    minimum: float
    maximum: float
    step: float | str
    unit: str | None = None


# The temperature and shape values (first options step).
SHAPE_TUNING = (
    Tuning(
        CONF_THERMOCLINE_WIDTH, DEFAULT_THERMOCLINE_WIDTH * 100, 10, 60, 1, PERCENTAGE
    ),
    Tuning("usable_fraction", DEFAULT_USABLE_FRACTION, 0.5, 0.98, 0.01),
    Tuning(
        "mix_temperature",
        DEFAULT_MIX_TEMPERATURE,
        25,
        60,
        0.5,
        UnitOfTemperature.CELSIUS,
    ),
    Tuning(
        "max_temperature",
        DEFAULT_MAX_TEMPERATURE,
        40,
        110,
        1,
        UnitOfTemperature.CELSIUS,
    ),
    Tuning("sensor_tolerance", DEFAULT_SENSOR_TOLERANCE, 0.1, 10, 0.1, "K"),
    Tuning("sensor_margin", DEFAULT_SENSOR_MARGIN, 0, 20, 0.1, "K"),
    Tuning(
        "ambient_temperature",
        DEFAULT_AMBIENT_TEMPERATURE,
        -10,
        50,
        0.5,
        UnitOfTemperature.CELSIUS,
    ),
    Tuning("cold_mean", DEFAULT_COLD_MEAN, 0, 30, 0.5, UnitOfTemperature.CELSIUS),
    Tuning("cold_amplitude", DEFAULT_COLD_AMPLITUDE, 0, 15, 0.5, "K"),
    Tuning("cold_coldest_day", DEFAULT_COLD_COLDEST_DAY, 1, 365, 1, "day"),
)
# The draw, loss and heat values (third options step).
DRAW_TUNING = (
    Tuning("loss_coefficient", DEFAULT_LOSS_COEFFICIENT, 0.001, 0.015, "any", "1/h"),
    Tuning("other_hot_share", DEFAULT_OTHER_HOT_SHARE, 0, 0.6, 0.01),
    Tuning(
        "startup_energy",
        DEFAULT_STARTUP_ENERGY,
        0,
        3,
        0.05,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    Tuning("shower_flow", DEFAULT_SHOWER_FLOW, 1, 30, 0.1, "L/min"),
    Tuning("humidity_rise", DEFAULT_HUMIDITY_RISE, 1, 40, 0.5, PERCENTAGE),
    Tuning("humidity_window", DEFAULT_HUMIDITY_WINDOW, 5, 720, 5, UnitOfTime.MINUTES),
    Tuning(
        "long_draw_minutes", DEFAULT_LONG_DRAW_MINUTES, 0, 60, 0.5, UnitOfTime.MINUTES
    ),
    Tuning(
        "reclassify_window", DEFAULT_RECLASSIFY_WINDOW, 1, 60, 1, UnitOfTime.MINUTES
    ),
    Tuning("session_gap", DEFAULT_SESSION_GAP, 5, 600, 5, UnitOfTime.SECONDS),
    Tuning("max_draw", DEFAULT_MAX_DRAW, 10, 1000, 10, "L"),
    Tuning("power_threshold", DEFAULT_POWER_THRESHOLD, 1, 5000, 10, "W"),
)

# The optional source entities, by key.
OPTIONAL_SOURCES = (
    CONF_ENERGY_COUNTER,
    CONF_POWER_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_FLOW_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_HUMIDITY_SENSORS,
    CONF_COLD_SENSOR,
)


def _number(
    unit: str | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | str = "any",
) -> selector.NumberSelector:
    """Return a number box. Without limits, the step validates the value instead."""
    config = selector.NumberSelectorConfig(
        step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    return selector.NumberSelector(config)


def _sensor(
    *device_classes: SensorDeviceClass, multiple: bool = False
) -> selector.EntitySelector:
    """Return an entity selector for sensors of the given device classes."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=SENSOR_DOMAIN,
            device_class=list(device_classes),
            multiple=multiple,
        )
    )


def _temperature() -> selector.EntitySelector:
    """Return an entity selector for temperature sensors."""
    return _sensor(SensorDeviceClass.TEMPERATURE)


def _tuning_fields(tunings: tuple[Tuning, ...]) -> dict[Any, Any]:
    """Return the schema fields of numeric tuning values, each with its default."""
    return {
        probatio.Required(t.key, default=t.default): _number(
            t.unit, minimum=t.minimum, maximum=t.maximum, step=t.step
        )
        for t in tunings
    }


def _tank_fields() -> dict[Any, Any]:
    """Return the fields of the tank step: volume, tank sensor and its height."""
    return {
        probatio.Required(CONF_VOLUME): _number("L"),
        probatio.Required(CONF_TANK_SENSOR): _temperature(),
        probatio.Required(
            CONF_SENSOR_HEIGHT, default=DEFAULT_SENSOR_HEIGHT * 100
        ): _number(PERCENTAGE),
    }


def _meter_fields() -> dict[Any, Any]:
    """Return the field of the water meter step."""
    return {
        probatio.Required(CONF_WATER_METER): _sensor(
            SensorDeviceClass.WATER, SensorDeviceClass.VOLUME
        )
    }


def _heat_fields() -> dict[Any, Any]:
    """Return the fields of the heat input step: heat sources, flow and return."""
    return {
        probatio.Optional(CONF_ENERGY_COUNTER): _sensor(SensorDeviceClass.ENERGY),
        probatio.Optional(CONF_POWER_SENSOR): _sensor(SensorDeviceClass.POWER),
        probatio.Optional(CONF_HEATING_ACTIVE): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=BINARY_SENSOR_DOMAIN)
        ),
        probatio.Optional(CONF_FLOW_SENSOR): _temperature(),
        probatio.Optional(CONF_RETURN_SENSOR): _temperature(),
    }


def _detection_fields() -> dict[Any, Any]:
    """Return the field of the shower detection step."""
    return {
        probatio.Optional(CONF_HUMIDITY_SENSORS): _sensor(
            SensorDeviceClass.HUMIDITY, multiple=True
        )
    }


def _cold_fields() -> dict[Any, Any]:
    """Return the field of the cold water step."""
    return {probatio.Optional(CONF_COLD_SENSOR): _temperature()}


def _learning_fields() -> dict[Any, Any]:
    """Return the fields of the learning step: the locks and the history days."""
    return {
        probatio.Optional(CONF_LOCKS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(PARAMETER_BOUNDS),
                multiple=True,
                translation_key=CONF_LOCKS,
            )
        ),
        probatio.Required(CONF_HISTORY_DAYS, default=DEFAULT_HISTORY_DAYS): _number(
            UnitOfTime.DAYS,
            minimum=MIN_HISTORY_DAYS,
            maximum=MAX_HISTORY_DAYS,
            step=1,
        ),
    }


def validate_tank(user_input: Mapping[str, Any]) -> dict[str, str]:
    """Check the volume and the sensor height. Returns the errors by field."""
    errors: dict[str, str] = {}
    if not MIN_VOLUME <= float(user_input[CONF_VOLUME]) <= MAX_VOLUME:
        errors[CONF_VOLUME] = "volume_out_of_range"
    if (
        not MIN_SENSOR_HEIGHT
        <= float(user_input[CONF_SENSOR_HEIGHT])
        <= MAX_SENSOR_HEIGHT
    ):
        errors[CONF_SENSOR_HEIGHT] = "height_out_of_range"
    return errors


def validate_water_meter(hass: HomeAssistant, entity_id: str) -> dict[str, str]:
    """Check that the water meter has a volume unit.

    A meter that is unavailable (or not there yet) has nothing to check: its unit is
    checked again whenever a reading arrives, and a reading with another unit is ignored.
    """
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return {}
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if litres_from_meter(1.0, unit) is None:
        return {CONF_WATER_METER: "water_meter_unit"}
    return {}


def validate_heat(user_input: Mapping[str, Any]) -> dict[str, str]:
    """Check the heat input: one source at least, and flow and return as a pair."""
    errors: dict[str, str] = {}
    if not any(
        user_input.get(key)
        for key in (CONF_ENERGY_COUNTER, CONF_POWER_SENSOR, CONF_HEATING_ACTIVE)
    ):
        errors["base"] = "no_heat_source"
    if bool(user_input.get(CONF_FLOW_SENSOR)) != bool(
        user_input.get(CONF_RETURN_SENSOR)
    ):
        errors["base"] = "flow_return_pair"
    return errors


class HotWaterTankEstimatorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow: one entry per tank."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing collected."""
        self._name = ""
        self._options: dict[str, Any] = {}

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        """Return the options flow."""
        return HotWaterTankEstimatorOptionsFlow()

    def _form(
        self,
        step_id: str,
        fields: dict[Any, Any],
        user_input: Mapping[str, Any] | None,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show a form, keeping what the user entered when it is shown again."""
        schema = self.add_suggested_values_to_schema(
            probatio.Schema(fields), user_input
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: the tank's name and volume, and its sensor with the sensor's height."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_tank(user_input)
            if not errors:
                self._async_abort_entries_match(
                    {CONF_TANK_SENSOR: user_input[CONF_TANK_SENSOR]}
                )
                self._name = user_input[CONF_NAME]
                self._options.update(
                    {k: v for k, v in user_input.items() if k != CONF_NAME}
                )
                return await self.async_step_water_meter()
        fields = {
            probatio.Required(CONF_NAME): selector.TextSelector(),
            **_tank_fields(),
        }
        return self._form("user", fields, user_input, errors)

    async def async_step_water_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: the whole-house water meter."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_water_meter(self.hass, user_input[CONF_WATER_METER])
            if not errors:
                self._options.update(user_input)
                return await self.async_step_heat()
        return self._form("water_meter", _meter_fields(), user_input, errors)

    async def async_step_heat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: the heat input, with the heater's flow and return temperatures."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_heat(user_input)
            if not errors:
                self._options.update(user_input)
                return await self.async_step_detection()
        return self._form("heat", _heat_fields(), user_input, errors)

    async def async_step_detection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: the bathroom humidity sensors."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_cold()
        return self._form("detection", _detection_fields(), user_input)

    async def async_step_cold(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 5: the cold water sensor. This creates the entry."""
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(
                title=self._name, data={}, options=self._options
            )
        return self._form("cold", _cold_fields(), user_input)


class HotWaterTankEstimatorOptionsFlow(OptionsFlowWithReload):
    """Handle the options: the tank, the sources, the draw values and the learning.

    The entry reloads when the options change. The model state survives through the restore
    data of the tank average sensor and the calibration through the store.
    """

    def __init__(self) -> None:
        """Start with no options loaded."""
        self._options: dict[str, Any] = {}

    def _form(
        self,
        step_id: str,
        fields: dict[Any, Any],
        user_input: Mapping[str, Any] | None,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show a form with the current options, or what the user entered when it is shown again."""
        schema = self.add_suggested_values_to_schema(
            probatio.Schema(fields),
            user_input if user_input is not None else self._options,
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    def _store(self, user_input: Mapping[str, Any], fields: dict[Any, Any]) -> None:
        """Keep what a step returned. A cleared optional field is dropped."""
        for marker in fields:
            self._options.pop(marker.schema, None)
        self._options.update(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Tank, sensor height and the temperature and shape values."""
        if not self._options:
            self._options = dict(self.config_entry.options)
        fields = {**_tank_fields(), **_tuning_fields(SHAPE_TUNING)}
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_tank(user_input)
            if not errors:
                self._store(user_input, fields)
                return await self.async_step_sources()
        return self._form("init", fields, user_input, errors)

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The water meter and the optional sources."""
        fields = {
            **_meter_fields(),
            **_heat_fields(),
            **_detection_fields(),
            **_cold_fields(),
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_water_meter(self.hass, user_input[CONF_WATER_METER])
            errors |= validate_heat(user_input)
            if not errors:
                self._store(user_input, fields)
                return await self.async_step_draws()
        return self._form("sources", fields, user_input, errors)

    async def async_step_draws(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The draw, loss and heat values."""
        fields = _tuning_fields(DRAW_TUNING)
        if user_input is not None:
            self._store(user_input, fields)
            return await self.async_step_learning()
        return self._form("draws", fields, user_input)

    async def async_step_learning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The locks on learned parameters, and the days of history for the setup fit."""
        fields = _learning_fields()
        if user_input is not None:
            self._store(user_input, fields)
            return self.async_create_entry(data=self._options)
        return self._form("learning", fields, user_input)
