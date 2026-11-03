"""Sensors of a tank: the estimate, and the calibration diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass

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
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .calibration import (
    LOSS_COEFFICIENT,
    OTHER_HOT_SHARE,
    STARTUP_ENERGY,
    THERMOCLINE_WIDTH,
    USABLE_FRACTION,
)
from .entity import TankEntity
from .estimator import TankConfigEntry, TankEstimator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TankSensorDescription(SensorEntityDescription):
    """A sensor of the tank and how to read its value."""

    value_fn: Callable[[TankEstimator], float | int | None]
    parameter: str | None = (
        None  # the learned parameter shown, for the source attribute
    )


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
    def native_value(self) -> float | int | None:
        """Return the value."""
        return self.entity_description.value_fn(self.estimator)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return where a calibration parameter's value comes from."""
        parameter = self.entity_description.parameter
        if parameter is None:
            return None
        return {"source": self.estimator.calibrator.source_of(parameter)}
