"""The PIN programming event of the Yale Access Bluetooth Keypad integration."""

from typing import override

from homeassistant.components.event import EventEntity
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTR_NAME, ATTR_PIN, ATTR_SLOT, EVENT_PIN_CLEARED, EVENT_PIN_SET
from .models import YaleXSBLEKeypadConfigEntry, YaleXSBLEKeypadData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleXSBLEKeypadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the PIN programming event."""
    async_add_entities([YaleXSBLEKeypadProgrammingEvent(entry.runtime_data)])


class YaleXSBLEKeypadProgrammingEvent(EventEntity):
    """The event entity that records each PIN the actions set or clear on the entry's lock."""

    _attr_event_types = [EVENT_PIN_SET, EVENT_PIN_CLEARED]
    _attr_translation_key = "programming"
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: YaleXSBLEKeypadData) -> None:
        """Initialize the event entity."""
        self._data = data
        self._attr_unique_id = f"{data.address}_programming"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, data.address)},
            name=f"{data.title} Keypad",
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Let the actions record on this entity."""
        await super().async_added_to_hass()
        self._data.programming_event = self

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Stop the actions recording on this entity."""
        self._data.programming_event = None
        await super().async_will_remove_from_hass()

    @callback
    def async_record(
        self,
        context: Context,
        event_type: str,
        slot: int,
        name: str | None,
        pin: str | None,
    ) -> None:
        """Write a PIN set or clear under the context of the action call."""
        self.async_set_context(context)
        self._trigger_event(
            event_type, {ATTR_SLOT: slot, ATTR_NAME: name, ATTR_PIN: pin}
        )
        self.async_write_ha_state()
