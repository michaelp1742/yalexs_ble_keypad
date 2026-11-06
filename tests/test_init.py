"""Tests for the Yale Access Bluetooth Keypad setup and lifecycle."""

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from . import ADDRESS, TITLE, async_advance


async def test_core_unload_reloads_entry_until_core_loads(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Core's unload reloads the entry, which waits for core's next load."""
    old_lock = owner_entry.runtime_data.lock
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.reason == "Yale Access Bluetooth has not loaded this lock"

    assert await hass.config_entries.async_setup(owner_entry.entry_id)
    await async_advance(hass, freezer, 6)

    assert config_entry.state is ConfigEntryState.LOADED
    new_lock = owner_entry.runtime_data.lock
    assert new_lock is not old_lock
    assert config_entry.runtime_data.lock is new_lock


async def test_core_change_reaches_the_next_listener(
    hass: HomeAssistant, owner_entry: MockConfigEntry, config_entry: MockConfigEntry
) -> None:
    """The entry's reload waits until core's entry has called every listener."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    seen: list[tuple[ConfigEntryState, ConfigEntryState]] = []
    owner_entry.async_on_state_change(
        lambda: seen.append((owner_entry.state, config_entry.state))
    )

    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert seen == [
        (ConfigEntryState.UNLOAD_IN_PROGRESS, ConfigEntryState.LOADED),
        (ConfigEntryState.NOT_LOADED, ConfigEntryState.LOADED),
    ]
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_core_change_reloads_entry_once(
    hass: HomeAssistant, owner_entry: MockConfigEntry, config_entry: MockConfigEntry
) -> None:
    """Each reload or unload of core's entry reloads the entry once."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    data = config_entry.runtime_data
    assert (data.title, data.address, data.lock) == (
        TITLE,
        ADDRESS,
        owner_entry.runtime_data.lock,
    )
    states: list[ConfigEntryState] = []
    config_entry.async_on_state_change(lambda: states.append(config_entry.state))

    assert await hass.config_entries.async_reload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert states.count(ConfigEntryState.SETUP_IN_PROGRESS) == 1
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.lock is owner_entry.runtime_data.lock

    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert states.count(ConfigEntryState.SETUP_IN_PROGRESS) == 2
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
