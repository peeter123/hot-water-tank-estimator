"""The "Shower flow" number: the flow that turns shower litres into minutes."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .calibration import PARAMETER_BOUNDS, SHOWER_FLOW, SOURCE_OPTION
from .entity import TankEntity
from .estimator import TankConfigEntry, TankEstimator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the number."""
    async_add_entities([ShowerFlowNumber(entry.runtime_data)])


class ShowerFlowNumber(TankEntity, NumberEntity):
    """The shower flow in use. Setting it locks the flow at that value."""

    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.LITERS_PER_MINUTE
    _attr_native_min_value, _attr_native_max_value = PARAMETER_BOUNDS[SHOWER_FLOW]
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, estimator: TankEstimator) -> None:
        """Create the number."""
        super().__init__(estimator, "shower_flow")

    @property
    def native_value(self) -> float:
        """Return the shower flow in use in L/min."""
        return round(self.estimator.calibrator.value_of(SHOWER_FLOW), 2)

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Return where the flow comes from, and the lowest and highest flow of the history."""
        calibrator = self.estimator.calibrator
        flows = calibrator.shower_flows
        source = calibrator.source_of(SHOWER_FLOW)
        return {
            "source": "default" if source == SOURCE_OPTION else source,
            "low": round(min(flows), 2) if flows else None,
            "high": round(max(flows), 2) if flows else None,
        }

    async def async_set_native_value(self, value: float) -> None:
        """Keep the flow and lock it."""
        await self.estimator.async_set_shower_flow(value)
