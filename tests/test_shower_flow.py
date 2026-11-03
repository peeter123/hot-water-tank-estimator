"""Tests for the shower flow in the runtime: the number, its lock, the options and the live minutes."""

from datetime import timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hot_water_tank_estimator.calibration import Calibrator
from custom_components.hot_water_tank_estimator.const import (
    CONF_LOCKS,
    DOMAIN,
    STORAGE_VERSION,
)
from custom_components.hot_water_tank_estimator.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.hot_water_tank_estimator.model import (
    EventKind,
    ModelOptions,
    TankModel,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .common import (
    FULL_OPTIONS,
    FULL_SOURCES,
    HUMIDITY,
    METER,
    Rig,
    entity_id,
    set_sources,
    setup_entry,
    value,
)
from .test_calibration_runtime import WEEK_END, held_fit, start_while_fitting
from .test_options_flow import walk

ENTRY_ID = "shower-entry-id"
TWO_PEOPLE = (7.4, 7.6, 7.5, 12.1, 11.8, 7.3, 12.0, 7.7, 11.9, 7.5)


def calibration_with_history() -> Calibrator:
    """Return a calibrator whose history is the two-people scenario: median 7.65 L/min."""
    calibrator = Calibrator(ModelOptions(volume=281.0))
    for flow in TWO_PEOPLE:
        calibrator.on_shower(flow * 5, 5.0)
    return calibrator


async def start_with_history(
    hass: HomeAssistant,
    freezer,
    hass_storage: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    """Set up an entry whose store holds the two-people history."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY_ID}",
        "data": {
            "calibrator": calibration_with_history().to_dict(),
            "fit_done": True,
            "ambient_fit": None,
        },
    }
    return await setup_entry(hass, options, entry_id=ENTRY_ID)


def number_state(hass: HomeAssistant, entry: MockConfigEntry):
    """Return the state of the shower flow number."""
    state = hass.states.get(entity_id(hass, entry, "number", "shower_flow"))
    assert state is not None
    return state


async def set_number(hass: HomeAssistant, entry: MockConfigEntry, flow: float) -> None:
    """Set the shower flow number."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id(hass, entry, "number", "shower_flow"), "value": flow},
        blocking=True,
    )
    await hass.async_block_till_done()


async def feed(
    hass: HomeAssistant, freezer, entity: str, state: str, after: float
) -> None:
    """Advance time, change a source and wait."""
    freezer.tick(timedelta(seconds=after))
    attributes = hass.states.get(entity).attributes if hass.states.get(entity) else {}
    hass.states.async_set(entity, state, attributes)
    await hass.async_block_till_done()


async def run_shower(hass: HomeAssistant, freezer) -> None:
    """A shower of 25 readings of 1 L: 24 L over 4 minutes of flow (6.0 L/min), detected by humidity."""
    await feed(hass, freezer, HUMIDITY, "72.0", 60)
    reading = float(hass.states.get(METER).state)
    for _ in range(25):
        reading += 0.001
        await feed(hass, freezer, METER, f"{reading:.3f}", 10)
    await feed(hass, freezer, HUMIDITY, "55.0", 300)


async def test_the_default_shower_flow(hass: HomeAssistant) -> None:
    """Without a learned flow the number shows the default 7.5 L/min, from the default source."""
    set_sources(hass)
    entry = await setup_entry(hass)
    state = number_state(hass, entry)
    assert state.state == "7.5"
    assert state.attributes["source"] == "default"
    assert state.attributes["low"] is None
    assert state.attributes["high"] is None


async def test_the_number_shows_the_learned_flow(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """The history of two people shows 7.65 L/min, learned, from 7.3 to 12.1."""
    entry = await start_with_history(hass, freezer, hass_storage)
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "learned"
    assert state.attributes["low"] == 7.3
    assert state.attributes["high"] == 12.1
    minutes = hass.states.get(entity_id(hass, entry, "sensor", "shower_minutes"))
    assert minutes is not None
    assert minutes.attributes["flow"] == 7.65
    assert minutes.attributes["flow_basis"] == "median"
    assert minutes.attributes["minutes_low"] <= int(minutes.state)
    assert minutes.attributes["minutes_high"] >= int(minutes.state)


async def test_a_shower_adds_to_the_history(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """A detected shower of 4 minutes of flow is a sample: the history, the number and the event."""
    entry = await start_with_history(hass, freezer, hass_storage)
    await run_shower(hass, freezer)
    estimator = entry.runtime_data
    assert estimator.calibrator.shower_flows[-1] == pytest.approx(24 / 4)
    assert len(estimator.calibrator.shower_flows) == 10
    state = number_state(hass, entry)
    assert state.attributes["low"] == 6.0
    assert state.state == "7.65"
    kinds = [e["kind"] for e in estimator.recent_events()]
    assert "shower_flow" in kinds
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["calibration"]["shower_flow_history"][-1] == pytest.approx(6.0)


async def test_set_the_shower_flow(hass: HomeAssistant, freezer, hass_storage) -> None:
    """Learned 7.65, set to 9: 9 locked, in the options too, and later showers add to the history."""
    entry = await start_with_history(hass, freezer, hass_storage)
    await set_number(hass, entry, 9)
    state = number_state(hass, entry)
    assert state.state == "9.0"
    assert state.attributes["source"] == "locked"
    assert "shower_flow" in entry.options[CONF_LOCKS]
    estimator = entry.runtime_data
    assert estimator.model.options.shower_flow == 9.0
    assert estimator.config.locks == {"shower_flow"}
    events = [
        e for e in estimator.recent_events() if e["kind"] == EventKind.SHOWER_FLOW
    ]
    assert events[-1]["change"] == {"result": "set", "old": 7.65, "new": 9.0}

    await run_shower(hass, freezer)
    state = number_state(hass, entry)
    assert state.state == "9.0"
    assert state.attributes["source"] == "locked"
    assert state.attributes["low"] == 6.0
    assert estimator.calibrator.shower_flows[-1] == pytest.approx(24 / 4)
    minutes = hass.states.get(entity_id(hass, entry, "sensor", "shower_minutes"))
    assert minutes is not None
    assert minutes.attributes["flow"] == 9.0


async def test_the_set_flow_survives_a_reload(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """A reload keeps the flow locked at 9: the options lock and the stored value agree."""
    entry = await start_with_history(hass, freezer, hass_storage)
    await set_number(hass, entry, 9)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = number_state(hass, entry)
    assert state.state == "9.0"
    assert state.attributes["source"] == "locked"
    assert entry.runtime_data.calibrator.shower_flows == list(TWO_PEOPLE)


async def test_the_number_is_limited_to_its_bounds(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """A value outside 3-20 L/min is refused by the number."""
    entry = await start_with_history(hass, freezer, hass_storage)
    with pytest.raises(ServiceValidationError, match="outside valid range"):
        await set_number(hass, entry, 25)
    assert number_state(hass, entry).state == "7.65"


async def test_unlock_in_the_options(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """Locked at 9, the lock turned off in the options: the median again, learned."""
    entry = await start_with_history(hass, freezer, hass_storage)
    await set_number(hass, entry, 9)
    result = await walk(hass, entry.entry_id, learning={CONF_LOCKS: []})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "learned"
    assert entry.options[CONF_LOCKS] == []


async def test_lock_in_the_options_holds_the_flow_in_use(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """The shower flow lock of the options form holds the value in use, and the history keeps filling."""
    entry = await start_with_history(hass, freezer, hass_storage)
    result = await walk(hass, entry.entry_id, learning={CONF_LOCKS: ["shower_flow"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "locked"
    await run_shower(hass, freezer)
    assert number_state(hass, entry).state == "7.65"
    assert entry.runtime_data.calibrator.shower_flows[-1] == pytest.approx(24 / 4)


async def test_the_options_form_has_no_shower_flow_value(hass: HomeAssistant) -> None:
    """The draws step has no shower flow field, and the lock selector offers it."""
    set_sources(hass)
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    for data in ({"sensor_height": 50}, {}):
        result = await hass.config_entries.options.async_configure(flow_id, data)
    assert result["step_id"] == "draws"
    assert "shower_flow" not in {str(key) for key in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(flow_id, {})
    assert result["step_id"] == "learning"
    selector = next(
        marker for marker in result["data_schema"].schema if str(marker) == CONF_LOCKS
    )
    assert "shower_flow" in result["data_schema"].schema[selector].config["options"]


async def test_an_old_shower_flow_option_is_the_starting_value(
    hass: HomeAssistant, freezer
) -> None:
    """An entry saved with a shower flow of 9 starts at 9 until the first shower is learned."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    entry = await setup_entry(hass, {**FULL_OPTIONS, "shower_flow": 9.0})
    state = number_state(hass, entry)
    assert state.state == "9.0"
    assert state.attributes["source"] == "default"
    await run_shower(hass, freezer)
    state = number_state(hass, entry)
    assert state.state == "6.0"
    assert state.attributes["source"] == "learned"


async def test_a_store_without_the_shower_flow_state_loads(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """A store saved before the history and the shower in progress existed loads."""
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    model = TankModel(
        ModelOptions(volume=281.0), FULL_SOURCES, dt_util.utcnow(), 41.2, 56.0
    )
    model_state = model.to_dict()
    del model_state["classifier"]["shower"]
    calibrator_state = Calibrator(ModelOptions(volume=281.0)).to_dict()
    del calibrator_state["shower_flow_history"]
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY_ID}",
        "data": {
            "model": model_state,
            "calibrator": calibrator_state,
            "fit_done": True,
        },
    }
    entry = await setup_entry(hass, entry_id=ENTRY_ID)
    assert entry.runtime_data.model_restored
    state = number_state(hass, entry)
    assert state.state == "7.5"
    assert state.attributes["source"] == "default"


async def test_the_minutes_follow_the_flow_of_the_shower_in_progress(
    hass: HomeAssistant, freezer
) -> None:
    """Every meter reading during a shower updates the minutes: the median first, then the shower's flow."""
    rig = await Rig.start(hass, freezer)
    updates: list[None] = []

    @callback
    def count() -> None:
        updates.append(None)

    unsubscribe = async_dispatcher_connect(hass, rig.entry.runtime_data.signal, count)
    await rig.set(HUMIDITY, "72.0", after=60)
    reading = 100.000
    seen: list[tuple[str, float]] = []
    for _ in range(10):  # 1 L every 10 s: 6.0 L/min
        reading += 0.001
        before = len(updates)
        await rig.set(METER, f"{reading:.3f}", after=10)
        assert len(updates) > before
        rig.check()
        state = hass.states.get(entity_id(hass, rig.entry, "sensor", "shower_minutes"))
        assert state is not None
        seen.append((state.attributes["flow_basis"], state.attributes["flow"]))
    unsubscribe()
    assert seen[0] == ("median", 7.5)
    assert seen[-1] == ("current_shower", 6.0)
    # The first minute of flow is the 7th reading: 6 intervals of 10 s.
    assert [basis for basis, _ in seen].index("current_shower") == 6
    state = hass.states.get(entity_id(hass, rig.entry, "sensor", "shower_minutes"))
    assert state is not None
    assert state.attributes["minutes_low"] == state.attributes["minutes_high"]
    await rig.set(HUMIDITY, "55.0", after=300)
    state = hass.states.get(entity_id(hass, rig.entry, "sensor", "shower_minutes"))
    assert state is not None
    assert state.attributes["flow_basis"] == "median"


async def test_a_shower_learned_during_a_fit_is_kept(
    hass: HomeAssistant, freezer
) -> None:
    """The sample of a shower detected while the fit ran is added to the replay's history."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        entry.runtime_data.calibrator.on_shower(40.0, 4.0)
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.calibrator.shower_flows[-1] == pytest.approx(10.0)
    assert len(entry.runtime_data.calibrator.shower_flows) <= 10


async def test_a_flow_set_during_a_fit_stays_locked(
    hass: HomeAssistant, freezer
) -> None:
    """The flow set by hand while the fit ran is still locked, in the calibrator and the options."""
    gate, install = held_fit()
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        await set_number(hass, entry, 11.0)
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    state = number_state(hass, entry)
    assert state.state == "11.0"
    assert state.attributes["source"] == "locked"
    assert "shower_flow" in entry.options[CONF_LOCKS]
    assert value(hass, entry, "sensor", "calibration_samples") == "7", (
        "the fit itself was applied"
    )


async def test_the_options_flow_saves_with_an_old_shower_flow_key(
    hass: HomeAssistant,
) -> None:
    """An entry saved with a shower flow option opens the form and saves; the key does not break validation."""
    set_sources(hass)
    entry = await setup_entry(hass, {**FULL_OPTIONS, "shower_flow": 9.0})
    result = await walk(hass, entry.entry_id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert number_state(hass, entry).state == "9.0"


async def set_switch(hass: HomeAssistant, entry: MockConfigEntry, on: bool) -> None:
    """Turn the shower flow locked switch on or off."""
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": entity_id(hass, entry, "switch", "shower_flow_locked")},
        blocking=True,
    )
    await hass.async_block_till_done()


def switch_state(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Return the state of the shower flow locked switch."""
    state = hass.states.get(entity_id(hass, entry, "switch", "shower_flow_locked"))
    assert state is not None
    return state.state


def flow_events(entry: MockConfigEntry) -> list[dict[str, Any]]:
    """Return the logged shower flow events, oldest first."""
    return [
        e
        for e in entry.runtime_data.recent_events()
        if e["kind"] == EventKind.SHOWER_FLOW
    ]


async def test_lock_the_learned_flow(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """Learned 7.65, switch on: 7.65 locked, in the options, and later showers do not change it."""
    entry = await start_with_history(hass, freezer, hass_storage)
    assert switch_state(hass, entry) == "off"
    updates: list[None] = []

    @callback
    def count() -> None:
        updates.append(None)

    unsubscribe = async_dispatcher_connect(hass, entry.runtime_data.signal, count)
    await set_switch(hass, entry, True)
    unsubscribe()
    assert updates
    assert switch_state(hass, entry) == "on"
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "locked"
    assert "shower_flow" in entry.options[CONF_LOCKS]
    estimator = entry.runtime_data
    assert estimator.config.locks == {"shower_flow"}
    assert flow_events(entry)[-1]["change"] == {"result": "locked", "flow": 7.65}

    await run_shower(hass, freezer)
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "locked"
    assert state.attributes["low"] == 6.0
    assert estimator.calibrator.shower_flows[-1] == pytest.approx(24 / 4)
    assert len(estimator.calibrator.shower_flows) == 10


async def test_setting_the_number_turns_the_switch_on(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """The number set to 9: the switch is on and 9 is locked."""
    entry = await start_with_history(hass, freezer, hass_storage)
    assert switch_state(hass, entry) == "off"
    await set_number(hass, entry, 9)
    assert switch_state(hass, entry) == "on"
    state = number_state(hass, entry)
    assert state.state == "9.0"
    assert state.attributes["source"] == "locked"


async def test_unlock_with_the_switch(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """Locked at 9, median 7.65, switch off: the number shows 7.65 learned and the options lock is off."""
    entry = await start_with_history(hass, freezer, hass_storage)
    await set_number(hass, entry, 9)
    updates: list[None] = []

    @callback
    def count() -> None:
        updates.append(None)

    unsubscribe = async_dispatcher_connect(hass, entry.runtime_data.signal, count)
    await set_switch(hass, entry, False)
    unsubscribe()
    assert updates
    assert switch_state(hass, entry) == "off"
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "learned"
    assert "shower_flow" not in entry.options[CONF_LOCKS]
    estimator = entry.runtime_data
    assert estimator.config.locks == frozenset()
    assert estimator.model.options.shower_flow == 7.65
    minutes = hass.states.get(entity_id(hass, entry, "sensor", "shower_minutes"))
    assert minutes is not None
    assert minutes.attributes["flow"] == 7.65
    assert flow_events(entry)[-1]["change"] == {"result": "unlocked", "flow": 7.65}
    assert len(estimator.calibrator.shower_flows) == 10


async def test_unlock_with_an_empty_history(hass: HomeAssistant) -> None:
    """Locked at 9 with no showers, then unlocked: 7.5 from the default source."""
    set_sources(hass)
    entry = await setup_entry(hass)
    await set_switch(hass, entry, True)
    state = number_state(hass, entry)
    assert state.state == "7.5"
    assert state.attributes["source"] == "locked"
    await set_number(hass, entry, 9)
    await set_switch(hass, entry, False)
    assert switch_state(hass, entry) == "off"
    state = number_state(hass, entry)
    assert state.state == "7.5"
    assert state.attributes["source"] == "default"


async def test_lock_in_the_options_turns_the_switch_on(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """The lock in the options: the switch is on after the reload, and off again when it is removed."""
    entry = await start_with_history(hass, freezer, hass_storage)
    result = await walk(hass, entry.entry_id, learning={CONF_LOCKS: ["shower_flow"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert switch_state(hass, entry) == "on"
    result = await walk(hass, entry.entry_id, learning={CONF_LOCKS: []})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert switch_state(hass, entry) == "off"


async def test_the_switch_survives_a_reload(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """Locked by the switch, it is on after a reload; unlocked, it is off after one."""
    entry = await start_with_history(hass, freezer, hass_storage)
    await set_switch(hass, entry, True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert switch_state(hass, entry) == "on"
    assert number_state(hass, entry).attributes["source"] == "locked"
    await set_switch(hass, entry, False)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert switch_state(hass, entry) == "off"
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "learned"


async def test_the_switch_is_a_config_entity(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """The switch is in the config category, and turning it on twice logs one event."""
    entry = await start_with_history(hass, freezer, hass_storage)
    entity = er.async_get(hass).async_get(
        entity_id(hass, entry, "switch", "shower_flow_locked")
    )
    assert entity is not None
    assert entity.entity_category is EntityCategory.CONFIG
    await set_switch(hass, entry, True)
    await set_switch(hass, entry, True)
    assert len(flow_events(entry)) == 1


async def test_a_lock_removed_during_a_fit_stays_removed(
    hass: HomeAssistant, freezer
) -> None:
    """The switch turned off while the fit's job runs: the applied fit has no lock, in the calibrator or the options."""
    gate, install = held_fit()
    unlock: list[Any] = []
    run_fit = gate.fit

    def fit_and_unlock(*args: Any, **kwargs: Any):
        result = run_fit(*args, **kwargs)
        unlock.append(
            hass.async_create_task(
                hass.services.async_call(
                    "switch",
                    "turn_off",
                    {
                        "entity_id": entity_id(
                            hass, unlock_entry[0], "switch", "shower_flow_locked"
                        )
                    },
                    blocking=True,
                )
            )
        )
        return result

    unlock_entry: list[MockConfigEntry] = []
    gate.fit = fit_and_unlock  # type: ignore[method-assign]
    freezer.move_to(WEEK_END)
    with install(hass):
        entry = await start_while_fitting(hass, gate)
        unlock_entry.append(entry)
        await set_number(hass, entry, 11.0)
        assert switch_state(hass, entry) == "on"
        gate.release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert unlock
    assert switch_state(hass, entry) == "off"
    state = number_state(hass, entry)
    assert state.attributes["source"] in ("learned", "default")
    assert state.state != "11.0"
    assert "shower_flow" not in entry.runtime_data.calibrator.locks
    assert "shower_flow" not in entry.options[CONF_LOCKS]


async def test_the_entry_options_win_over_the_store(
    hass: HomeAssistant, freezer, hass_storage
) -> None:
    """A store and entry options that disagree on the lock start as the options say, both ways."""
    # The store says locked at 9, the options say unlocked.
    freezer.move_to("2026-10-15T10:00:00+00:00")
    set_sources(hass)
    calibrator = calibration_with_history()
    calibrator.set_shower_flow(9.0)
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY_ID}",
        "data": {
            "calibrator": calibrator.to_dict(),
            "locks": ["shower_flow"],
            "fit_done": True,
            "ambient_fit": None,
        },
    }
    entry = await setup_entry(hass, entry_id=ENTRY_ID)
    assert switch_state(hass, entry) == "off"
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "learned"
    await hass.config_entries.async_unload(entry.entry_id)

    # The store says unlocked, the options say locked.
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"]["data"] = {
        "calibrator": calibration_with_history().to_dict(),
        "locks": [],
        "fit_done": True,
        "ambient_fit": None,
    }
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_LOCKS: ["shower_flow"]}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert switch_state(hass, entry) == "on"
    state = number_state(hass, entry)
    assert state.state == "7.65"
    assert state.attributes["source"] == "locked"
