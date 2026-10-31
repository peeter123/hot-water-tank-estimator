"""Config flow for the Hot Water Tank Estimator integration.

This is a scaffold: the steps arrive with the config flow task.
"""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class HotWaterTankEstimatorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hot Water Tank Estimator."""

    VERSION = 1
