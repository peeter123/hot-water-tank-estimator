"""The actions of the integration: set_tank_state and recalibrate."""

import probatio

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_extract_config_entry_ids

from .const import (
    ATTR_CHARGED_TEMPERATURE,
    ATTR_DAYS,
    ATTR_TANK_AVERAGE,
    DOMAIN,
    MAX_HISTORY_DAYS,
    MIN_HISTORY_DAYS,
    SERVICE_RECALIBRATE,
    SERVICE_SET_TANK_STATE,
)
from .estimator import TankEstimator

SET_TANK_STATE_SCHEMA = cv.make_entity_service_schema(
    {
        probatio.Optional(ATTR_TANK_AVERAGE): probatio.Coerce(float),
        probatio.Optional(ATTR_CHARGED_TEMPERATURE): probatio.Coerce(float),
    }
)
RECALIBRATE_SCHEMA = cv.make_entity_service_schema(
    {
        probatio.Optional(ATTR_DAYS): probatio.All(
            probatio.Coerce(int), probatio.Range(MIN_HISTORY_DAYS, MAX_HISTORY_DAYS)
        ),
    }
)


async def _estimators(call: ServiceCall) -> list[TankEstimator]:
    """Return the estimators of the loaded tanks the call targets."""
    entry_ids = await async_extract_config_entry_ids(call)
    estimators = [
        entry.runtime_data
        for entry in call.hass.config_entries.async_loaded_entries(DOMAIN)
        if entry.entry_id in entry_ids
    ]
    if not estimators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_tank_targeted"
        )
    return estimators


async def _set_tank_state(call: ServiceCall) -> None:
    """Set the temperatures of the targeted tanks, or charge them to the tank sensor."""
    average = call.data.get(ATTR_TANK_AVERAGE)
    charged = call.data.get(ATTR_CHARGED_TEMPERATURE)
    estimators = await _estimators(call)
    if (
        average is None
        and charged is None
        and any(e.model.tank_sensor is None for e in estimators)
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="tank_sensor_unavailable"
        )
    for estimator in estimators:
        estimator.set_state(average, charged)


async def _recalibrate(call: ServiceCall) -> None:
    """Rerun the setup fit of the targeted tanks."""
    days = call.data.get(ATTR_DAYS)
    for estimator in await _estimators(call):
        if await estimator.async_setup_fit(days) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_history"
            )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TANK_STATE,
        _set_tank_state,
        schema=SET_TANK_STATE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RECALIBRATE, _recalibrate, schema=RECALIBRATE_SCHEMA
    )
