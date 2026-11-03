"""The "Hot water ran out" button and its undo."""

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
    async_add_entities(
        [
            HotWaterRanOutButton(entry.runtime_data),
            UndoHotWaterRanOutButton(entry.runtime_data),
        ]
    )


class HotWaterRanOutButton(TankEntity, ButtonEntity):
    """Teaches the usable fraction: the user observed that hot water ran out."""

    def __init__(self, estimator: TankEstimator) -> None:
        """Create the button."""
        super().__init__(estimator, "hot_water_ran_out")

    async def async_press(self) -> None:
        """Apply the press to the end of the last draw, or explain why it is ignored."""
        await self.estimator.async_hot_water_ran_out()


class UndoHotWaterRanOutButton(TankEntity, ButtonEntity):
    """Undoes the last "Hot water ran out" press while that is still possible."""

    def __init__(self, estimator: TankEstimator) -> None:
        """Create the button."""
        super().__init__(estimator, "undo_hot_water_ran_out")

    @property
    def available(self) -> bool:
        """Return whether there is a press to undo."""
        return self.estimator.undo_available()

    async def async_press(self) -> None:
        """Undo the last accepted press."""
        await self.estimator.async_undo_hot_water_ran_out()
