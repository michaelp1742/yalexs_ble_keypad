"""Tests for the Yale Access Bluetooth Keypad PIN programming event."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.yalexs_ble_keypad.const import DOMAIN
from homeassistant.components.config import device_registry as config_device_registry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import ADDRESS

EVENT_ENTITY_ID = "event.front_door_keypad_pin_programming"


async def test_programming_event_on_a_linked_device(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    owner_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """The entry adds the programming event, unknown and enabled, on a Keypad device linked to core's lock device, and its unload makes it unavailable."""
    core_device = device_registry.async_get_or_create(
        config_entry_id=owner_entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity = entity_registry.async_get(EVENT_ENTITY_ID)
    assert entity is not None
    assert entity.platform == DOMAIN
    assert entity.unique_id == f"{ADDRESS}_programming"
    assert entity.disabled_by is None
    state = hass.states.get(EVENT_ENTITY_ID)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["friendly_name"] == "Front Door Keypad PIN programming"
    assert state.attributes["event_types"] == ["pin_set", "pin_cleared"]
    assert "device_class" not in state.attributes
    device = device_registry.async_get(entity.device_id)
    assert device is not None
    assert device.config_entry_id == config_entry.entry_id
    assert device.connections == {(dr.CONNECTION_BLUETOOTH, ADDRESS)}
    assert device.name == "Front Door Keypad"

    config_device_registry.async_setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "config/device_registry/list_linked_devices",
            "device_id": core_device.id,
        }
    )
    msg = await client.receive_json()
    assert msg["result"]["linked_devices"] == [device.id]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert hass.states.get(EVENT_ENTITY_ID).state == STATE_UNAVAILABLE
