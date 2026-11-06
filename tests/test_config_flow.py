"""Tests for the Yale Access Bluetooth Keypad config flow."""

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yalexs_ble_keypad.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import ADDRESS, BACK_ADDRESS, BACK_TITLE, TITLE, async_setup_owner


def _listed_locks(result: dict[str, Any]) -> list[dict[str, str]]:
    """Return the locks the form offers."""
    return result["data_schema"].schema[CONF_ADDRESS].config["options"]


async def test_user_flow_adds_each_loaded_lock_once(hass: HomeAssistant) -> None:
    """Each loaded lock gets one entry with the title of core's entry, and none left aborts."""
    await async_setup_owner(hass)
    await async_setup_owner(hass, BACK_ADDRESS, BACK_TITLE)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert _listed_locks(result) == [
        {"value": ADDRESS, "label": TITLE},
        {"value": BACK_ADDRESS, "label": BACK_TITLE},
    ]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["options"] == {"cloud_pin_rules": False}
    assert result["result"].unique_id == ADDRESS

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert _listed_locks(result) == [{"value": BACK_ADDRESS, "label": BACK_TITLE}]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: BACK_ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == BACK_TITLE

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_locks"


@pytest.mark.usefixtures("owner_entry")
async def test_options_flow_stores_the_switches_and_reloads(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The options form offers each switch at its off value, and a submit stores the switches and reloads the entry."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    runtime_data = config_entry.runtime_data
    switches = {"cloud_pin_rules": True}

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({}) == {"cloud_pin_rules": False}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], switches
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == switches
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is not runtime_data
