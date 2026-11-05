"""Sensors of a tank: the estimate, and the calibration diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .calibration import (
    LOSS_COEFFICIENT,
    OTHER_HOT_SHARE,
    STARTUP_ENERGY,
    THERMOCLINE_WIDTH,
    USABLE_FRACTION,
    heat_capacity,
)
from .entity import TankEntity
from .estimator import TankConfigEntry, TankEstimator
from .setup_fit import TANK_TEMPERATURE

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TankSensorDescription(SensorEntityDescription):
    """A sensor of the tank and how to read its value."""

    value_fn: Callable[[TankEstimator], float | int | datetime | None]
    parameter: str | None = (
        None  # the learned parameter shown, for the source attribute
    )
    attributes_fn: Callable[[TankEstimator], dict[str, Any]] | None = None
    available_fn: Callable[[TankEstimator], bool] | None = (
        None  # unavailable while this is False
    )


def _heat_loss(estimator: TankEstimator) -> int:
    """Return the standing loss in W: k * C * max(0, t_avg - t_ambient) * 1000."""
    model = estimator.model
    options = model.options
    excess = max(0.0, model.t_avg - model.ambient_temperature(dt_util.utcnow()))
    return round(
        options.loss_coefficient * heat_capacity(options.volume) * excess * 1000
    )


def _shower_time_attributes(estimator: TankEstimator) -> dict[str, Any]:
    """Return the flow behind the shower minutes and the minutes at the extreme flows."""
    shower = estimator.model.shower_time
    return {
        "flow": round(shower.flow, 2),
        "flow_basis": shower.basis,
        "minutes_low": shower.low,
        "minutes_high": shower.high,
    }


def _tank_sensor_attributes(estimator: TankEstimator) -> dict[str, Any]:
    """Return the tank sensor's entity ID and the configured sensor height in %."""
    config = estimator.config
    source = next(
        entity_id
        for entity_id, roles in config.routes.items()
        if TANK_TEMPERATURE in roles
    )
    return {
        "source_entity": source,
        "sensor_height": round(config.options.sensor_height * 100, 1),
    }


ESTIMATE_SENSORS: tuple[TankSensorDescription, ...] = (
    TankSensorDescription(
        key="tank_litres",
        translation_key="hot_water_remaining",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda e: e.model.outputs.tank_litres,
    ),
    TankSensorDescription(
        key="shower_litres",
        translation_key="shower_litres",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda e: e.model.outputs.shower_litres,
    ),
    TankSensorDescription(
        key="percent_charged",
        translation_key="charge_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda e: e.model.outputs.percent_charged,
    ),
    TankSensorDescription(
        key="shower_minutes",
        translation_key="shower_minutes",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda e: e.model.outputs.shower_minutes,
        attributes_fn=_shower_time_attributes,
    ),
    TankSensorDescription(
        key="heat_loss",
        translation_key="heat_loss",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_heat_loss,
    ),
    TankSensorDescription(
        key="charged_temperature",
        translation_key="charged_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda e: round(e.model.t_ch, 2),
    ),
    TankSensorDescription(
        key="cold_water_temperature",
        translation_key="cold_water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda e: round(e.model.t_cold, 2),
    ),
)

TANK_AVERAGE = TankSensorDescription(
    key="tank_average",
    translation_key="tank_average",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
    value_fn=lambda e: round(e.model.t_avg, 2),
)


def _percent(estimator: TankEstimator, name: str) -> float:
    """Return a fraction parameter in use as a percentage."""
    return round(estimator.calibrator.value_of(name) * 100, 1)


DIAGNOSTIC_SENSORS: tuple[TankSensorDescription, ...] = (
    TankSensorDescription(
        key="other_hot_share",
        translation_key="other_hot_share",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        parameter=OTHER_HOT_SHARE,
        value_fn=lambda e: round(e.calibrator.value_of(OTHER_HOT_SHARE), 4),
    ),
    TankSensorDescription(
        key="startup_energy",
        translation_key="startup_energy",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        parameter=STARTUP_ENERGY,
        value_fn=lambda e: round(e.calibrator.value_of(STARTUP_ENERGY), 3),
    ),
    TankSensorDescription(
        key="loss_coefficient",
        translation_key="loss_coefficient",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="1/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        parameter=LOSS_COEFFICIENT,
        value_fn=lambda e: round(e.calibrator.value_of(LOSS_COEFFICIENT), 5),
    ),
    TankSensorDescription(
        key="thermocline_width",
        translation_key="thermocline_width",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        parameter=THERMOCLINE_WIDTH,
        value_fn=lambda e: _percent(e, THERMOCLINE_WIDTH),
    ),
    TankSensorDescription(
        key="usable_fraction",
        translation_key="usable_fraction",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        parameter=USABLE_FRACTION,
        value_fn=lambda e: _percent(e, USABLE_FRACTION),
    ),
    TankSensorDescription(
        key="tank_sensor_temperature",
        translation_key="tank_sensor_temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda e: (
            None if (reading := e.model.tank_sensor) is None else round(reading, 2)
        ),
        attributes_fn=_tank_sensor_attributes,
        available_fn=lambda e: e.fed and e.model.tank_sensor is not None,
    ),
    TankSensorDescription(
        key="shower_end_time",
        translation_key="shower_end_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda e: e.model.options.shower_end_minutes,
    ),
    TankSensorDescription(
        key="next_shower_time",
        translation_key="next_shower_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda e: e.model.options.next_shower_minutes,
        available_fn=lambda e: bool(e.model.sources.humidity_sensors),
    ),
    TankSensorDescription(
        key="shower_ends",
        translation_key="shower_ends",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda e: e.model.next_shower_end,
        available_fn=lambda e: e.model.detection_available,
    ),
    TankSensorDescription(
        key="draw_counts_as_shower",
        translation_key="draw_counts_as_shower",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda e: e.model.next_shower_start,
        available_fn=lambda e: e.model.detection_available,
    ),
    TankSensorDescription(
        key="calibration_samples",
        translation_key="calibration_samples",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.calibrator.sample_count,
    ),
    TankSensorDescription(
        key="last_charge_error",
        translation_key="last_charge_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="K",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda e: (
            None
            if e.calibrator.last_error is None
            else round(e.calibrator.last_error, 2)
        ),
    ),
    TankSensorDescription(
        key="mean_charge_error",
        translation_key="mean_charge_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="K",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda e: (
            None
            if (error := e.calibrator.mean_abs_error()) is None
            else round(error, 2)
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of a tank."""
    estimator = entry.runtime_data
    entities: list[SensorEntity] = [TankSensor(estimator, TANK_AVERAGE)]
    entities += [TankSensor(estimator, d) for d in ESTIMATE_SENSORS]
    entities += [TankSensor(estimator, d) for d in DIAGNOSTIC_SENSORS]
    async_add_entities(entities)


class TankSensor(TankEntity, SensorEntity):
    """A sensor whose value is read from the estimator."""

    entity_description: TankSensorDescription

    def __init__(
        self, estimator: TankEstimator, description: TankSensorDescription
    ) -> None:
        """Create the sensor."""
        super().__init__(estimator, description.key, description.translation_key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | datetime | None:
        """Return the value."""
        return self.entity_description.value_fn(self.estimator)

    @property
    def available(self) -> bool:
        """Return whether the sensor has a value: a reading-based sensor follows its source."""
        check = self.entity_description.available_fn
        return check is None or check(self.estimator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return where a calibration parameter's value comes from, or the sensor's own attributes."""
        description = self.entity_description
        if description.attributes_fn is not None:
            return description.attributes_fn(self.estimator)
        if description.parameter is None:
            return None
        return {"source": self.estimator.calibrator.source_of(description.parameter)}
