"""The "Shower ran cold" button."""

from homeassistant.components.button import ButtonEntity
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
    """Add the button."""
    async_add_entities([ShowerRanColdButton(entry.runtime_data)])


class ShowerRanColdButton(TankEntity, ButtonEntity):
    """Teaches the usable fraction: the user observed that the shower ran cold."""

    def __init__(self, estimator: TankEstimator) -> None:
        """Create the button."""
        super().__init__(estimator, "shower_ran_cold")

    async def async_press(self) -> None:
        """Set the usable fraction to the cold fraction now and empty the model."""
        self.estimator.cold_shower()
