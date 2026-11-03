"""The Hot Water Tank Estimator integration."""

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, STORAGE_VERSION
from .estimator import TankConfig, TankConfigEntry, TankEstimator
from .services import async_setup_services

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, which do not depend on a config entry."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TankConfigEntry) -> bool:
    """Set up one tank.

    The store holds the model state and the calibration. The estimator restores both, the
    platforms are set up, and only then does it start listening, so that the first readings
    apply to the restored model.
    """
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
    )
    estimator = TankEstimator(
        hass,
        entry,
        TankConfig.from_options(entry.options),
        store,
        await store.async_load(),
    )
    entry.runtime_data = estimator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    estimator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TankConfigEntry) -> bool:
    """Unload a tank, saving its model and calibration to the store."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TankConfigEntry) -> None:
    """Delete the store (model and calibration) of a removed tank."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
