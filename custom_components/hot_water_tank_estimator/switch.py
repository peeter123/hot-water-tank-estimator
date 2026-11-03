"""The "Shower flow locked" switch: the lock of the shower flow."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .calibration import SHOWER_FLOW
from .entity import TankEntity
from .estimator import TankConfigEntry, TankEstimator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switch."""
    async_add_entities([ShowerFlowLockedSwitch(entry.runtime_data)])


class ShowerFlowLockedSwitch(TankEntity, SwitchEntity):
    """Whether the shower flow is locked: the same lock as the number and the options."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, estimator: TankEstimator) -> None:
        """Create the switch."""
        super().__init__(estimator, "shower_flow_locked")

    @property
    def is_on(self) -> bool:
        """Return whether the shower flow is in the calibrator's locks."""
        return SHOWER_FLOW in self.estimator.calibrator.locks

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock the shower flow in use."""
        await self.estimator.async_set_shower_flow_locked(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Remove the lock: the flow is the median of the history again, or the default."""
        await self.estimator.async_set_shower_flow_locked(False)
