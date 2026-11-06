"""Storage for the keypad PINs the integration writes, each with its name."""

import asyncio
from dataclasses import dataclass
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1


@dataclass(frozen=True, kw_only=True)
class StoredPin:
    """A PIN the integration wrote to a slot, and the slot's name."""

    pin: str
    name: str | None


class _StoredPinData(TypedDict):
    """A slot's record in the store file."""

    pin: str
    name: str | None


def _async_get_store(
    hass: HomeAssistant, entry_id: str
) -> Store[dict[str, dict[str, _StoredPinData]]]:
    """Return the Store that holds a config entry's PINs."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.pins")


class PinStore:
    """The keypad PINs the integration wrote to the lock, by slot."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the PIN store."""
        self._hass = hass
        self._entry = entry
        self._store = _async_get_store(hass, entry.entry_id)
        self._pins: dict[int, StoredPin] = {}

    async def async_load(self) -> None:
        """Load the PINs from storage."""
        if data := await self._store.async_load():
            self._pins = {
                int(slot): StoredPin(pin=stored["pin"], name=stored["name"])
                for slot, stored in data["pins"].items()
            }

    def get(self, slot: int) -> StoredPin | None:
        """Return the PIN and name of a slot."""
        return self._pins.get(slot)

    async def async_set(self, slot: int, stored: StoredPin) -> None:
        """Set the PIN and name of a slot."""
        self._pins[slot] = stored
        await self._async_save()

    async def _async_save(self) -> None:
        """Save the PINs in an entry task, which unload waits for rather than cancels.

        Otherwise a cancelled save could finish writing after removal deleted the file.
        """
        task = self._entry.async_create_task(
            self._hass,
            self._store.async_save(
                {
                    "pins": {
                        str(slot): _StoredPinData(pin=stored.pin, name=stored.name)
                        for slot, stored in self._pins.items()
                    }
                }
            ),
            "yalexs_ble_keypad save pins",
        )
        await asyncio.shield(task)

    async def async_remove(self, slot: int) -> None:
        """Remove the PIN and name of a slot."""
        if self._pins.pop(slot, None) is not None:
            await self._async_save()


async def async_remove_pin_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the stored PINs of a config entry."""
    await _async_get_store(hass, entry_id).async_remove()
