"""Tests for the Yale Access Bluetooth Keypad config flow."""

from typing import Any

from custom_components.yalexs_ble_keypad.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
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
    assert result["options"] == {}
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
