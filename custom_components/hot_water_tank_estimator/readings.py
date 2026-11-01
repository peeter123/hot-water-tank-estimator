"""Reading a source state as the number the model takes."""

import math
from typing import Any

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import (
    EnergyConverter,
    PowerConverter,
    TemperatureConverter,
)

from .setup_fit import (
    COLD_WATER_TEMPERATURE,
    DHW_ENERGY,
    DHW_POWER,
    FLOW_TEMPERATURE,
    RETURN_TEMPERATURE,
    TANK_TEMPERATURE,
)

_TEMPERATURE_ROLES = {
    TANK_TEMPERATURE,
    FLOW_TEMPERATURE,
    RETURN_TEMPERATURE,
    COLD_WATER_TEMPERATURE,
}


def convert_reading(role: str, text: str, unit: str | None) -> float | None:
    """Return a state's number in the unit the model uses, None when it is not numeric.

    Temperatures go to C, the energy counter to kWh and the power sensor to W. The water meter
    and the humidity are returned as they are: the model converts the meter's unit itself.

    Args:
        role: The role of the source (the constants of `setup_fit`).
        text: The state text.
        unit: The unit of measurement of the state, None when it has none.

    Returns:
        The number, or None for an unavailable or non-numeric state.
    """
    try:
        value = float(text)
    except TypeError, ValueError:
        return None
    if not math.isfinite(value):
        return None
    converter: Any = None
    target = None
    if role in _TEMPERATURE_ROLES:
        converter, target = TemperatureConverter, UnitOfTemperature.CELSIUS
    elif role == DHW_ENERGY:
        converter, target = EnergyConverter, "kWh"
    elif role == DHW_POWER:
        converter, target = PowerConverter, "W"
    if converter is None or unit is None or unit == target:
        return value
    try:
        return float(converter.convert(value, unit, target))
    except HomeAssistantError:
        # A unit the converter does not know: use the number as it is.
        return value
