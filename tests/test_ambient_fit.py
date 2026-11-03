"""Tests for the ambient fit marker: when a start runs the setup fit because the ambient sensor changed."""

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.hot_water_tank_estimator.const import (
    CONF_AMBIENT_SENSOR,
    DOMAIN,
    STORAGE_VERSION,
)
from custom_components.hot_water_tank_estimator.estimator import TankEstimator
from custom_components.hot_water_tank_estimator.setup_fit import History
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .common import AMBIENT, FULL_OPTIONS, set_sources, setup_entry, setup_fitted_entry

READ = "custom_components.hot_water_tank_estimator.estimator.async_read_history"
ENTRY_ID = "marker-entry-id"


def empty_history() -> History:
    """A history without any rows: the fit finds nothing and ends."""
    now = dt_util.utcnow()
    return History(now - timedelta(days=30), now, [])


def prepare(hass: HomeAssistant) -> None:
    """Give the sources states, with a recorder (its history read is patched in the tests)."""
    set_sources(hass)
    hass.states.async_set(AMBIENT, "19.5", {"unit_of_measurement": "°C"})


@pytest.mark.parametrize(("configured", "runs"), [(False, False), (True, True)])
async def test_a_store_without_the_marker_counts_as_no_ambient_sensor(
    hass: HomeAssistant, hass_storage: dict[str, Any], configured: bool, runs: bool
) -> None:
    """With the fit done and no marker, a start fits only when an ambient sensor is configured."""
    prepare(hass)
    hass.config.components.add("recorder")
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY_ID}",
        "data": {"fit_done": True},
    }
    options = FULL_OPTIONS | ({CONF_AMBIENT_SENSOR: AMBIENT} if configured else {})
    with patch.object(
        TankEstimator, "async_setup_fit", new=AsyncMock(return_value=None)
    ) as fit:
        await setup_entry(hass, options, entry_id=ENTRY_ID)
        await hass.async_block_till_done()
    assert (fit.await_count == 1) is runs


async def test_a_real_fit_records_the_marker(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A fit that ran records the configured entity, and a later start runs no fit."""
    prepare(hass)
    entry = await setup_fitted_entry(
        hass, hass_storage, FULL_OPTIONS | {CONF_AMBIENT_SENSOR: AMBIENT}, None
    )
    assert entry.runtime_data.payload()["ambient_fit"] is None
    hass.config.components.add("recorder")
    read = AsyncMock(return_value=empty_history())
    with patch(READ, read):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    read.assert_awaited_once()
    assert entry.runtime_data.payload()["ambient_fit"] == AMBIENT
    again = AsyncMock(return_value=empty_history())
    with patch(READ, again):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    again.assert_not_awaited()


async def test_a_fit_stopped_midway_keeps_the_old_marker(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A stop while the history is read leaves the marker, so the next start fits again."""
    prepare(hass)
    entry = await setup_fitted_entry(
        hass, hass_storage, FULL_OPTIONS | {CONF_AMBIENT_SENSOR: AMBIENT}, None
    )
    hass.config.components.add("recorder")
    release = asyncio.Event()

    async def slow(*args: object) -> History:
        await release.wait()
        return empty_history()

    with patch(READ, AsyncMock(side_effect=slow)):
        await hass.config_entries.async_reload(entry.entry_id)
        await asyncio.sleep(0)
        # The reload stops the estimator again before the read returns.
        stopped = entry.runtime_data
        await hass.config_entries.async_unload(entry.entry_id)
        release.set()
        await hass.async_block_till_done()
    assert stopped.payload()["ambient_fit"] is None
    saved = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert saved["ambient_fit"] is None
    read = AsyncMock(return_value=empty_history())
    with patch(READ, read):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    read.assert_awaited_once()
    assert entry.runtime_data.payload()["ambient_fit"] == AMBIENT
