"""Read a tank's source history from the recorder, as the neutral `History` of the setup fit."""

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance, history
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant

from .readings import convert_reading
from .setup_fit import WATER_METER, History, Series

if TYPE_CHECKING:
    from .estimator import TankConfig


def _read(
    hass: HomeAssistant,
    routes: list[tuple[str, str]],
    start: datetime,
    end: datetime,
) -> History:
    """Return the history of the given `(entity_id, role)` sources.

    Runs in the recorder's executor. Each series starts with the state in force at `start`
    (when the entity existed then). The history starts at `start`, or at the first recorded
    state when the sources are younger than that.
    """
    series: list[Series] = []
    for entity_id, role in routes:
        changes = history.state_changes_during_period(
            hass, start, end, entity_id, include_start_time_state=True
        ).get(entity_id, [])
        rows: list[tuple[datetime, str]] = []
        unit: str | None = None
        for state in changes:
            state_unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if state_unit is not None:
                unit = state_unit
            value = convert_reading(role, state.state, state_unit)
            # Binary and unavailable states keep their text; numbers go in the model's unit.
            rows.append(
                (state.last_updated, state.state if value is None else repr(value))
            )
        if role != WATER_METER:
            # The numbers are in the model's unit now (C, kWh, W) or have none (humidity).
            unit = None
        series.append(Series(role, entity_id, unit, rows))
    first = min((s.states[0][0] for s in series if s.states), default=end)
    return History(max(start, first), end, series)


async def async_read_history(
    hass: HomeAssistant, config: TankConfig, start: datetime, end: datetime
) -> History:
    """Read the recorder history of a tank's sources and turn it into a `History`.

    The read and the conversion run in the recorder's executor.

    Args:
        hass: Home Assistant.
        config: The tank configuration, which says which entity plays which role.
        start: The first moment.
        end: The last moment.

    Returns:
        The history, with one series per source and role.
    """
    routes = [
        (entity_id, role)
        for entity_id, roles in config.routes.items()
        for role in roles
    ]
    return await get_instance(hass).async_add_executor_job(
        _read, hass, routes, start, end
    )
