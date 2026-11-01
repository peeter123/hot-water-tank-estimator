"""The base entity of a tank."""

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .estimator import TankEstimator


class TankEntity(Entity):
    """An entity of a tank: one device per entry, updated from the estimator's signal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, estimator: TankEstimator, key: str) -> None:
        """Create the entity.

        Args:
            estimator: The estimator of the tank.
            key: The translation key, also the unique ID suffix.
        """
        self.estimator = estimator
        self._attr_translation_key = key
        self._attr_unique_id = f"{estimator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, estimator.entry.entry_id)},
            name=estimator.entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Listen to the estimator."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.estimator.signal, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the new state."""
        self.async_write_ha_state()
