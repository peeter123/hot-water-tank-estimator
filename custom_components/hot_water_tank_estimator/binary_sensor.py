"""The shower detected binary sensor."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TankEntity
from .estimator import TankConfigEntry, TankEstimator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the shower detected binary sensor."""
    async_add_entities([ShowerDetectedSensor(entry.runtime_data)])


class ShowerDetectedSensor(TankEntity, BinarySensorEntity):
    """On while a shower or bath is detected; unavailable without a detection method."""

    def __init__(self, estimator: TankEstimator) -> None:
        """Create the binary sensor."""
        super().__init__(estimator, "shower_detected")

    @property
    def available(self) -> bool:
        """Return whether a detection method is configured."""
        return self.estimator.model.detection_available

    @property
    def is_on(self) -> bool:
        """Return whether a shower or bath is detected."""
        return self.estimator.model.shower_detected
