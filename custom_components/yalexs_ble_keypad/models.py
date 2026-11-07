"""Models for the Yale Access Bluetooth Keypad integration."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from yalexs_ble import PushLock

from homeassistant.config_entries import ConfigEntry

from .const import DEFAULT_OPTIONS
from .store import PinStore

if TYPE_CHECKING:
    from .event import YaleXSBLEKeypadProgrammingEvent


@dataclass(kw_only=True)
class YaleXSBLEKeypadData:
    """The runtime data of an entry: its title, its address, core's PushLock for the lock, its PIN store, and its programming event while that is added."""

    title: str
    address: str
    lock: PushLock
    pins: PinStore
    programming_event: YaleXSBLEKeypadProgrammingEvent | None = None


type YaleXSBLEKeypadConfigEntry = ConfigEntry[YaleXSBLEKeypadData]


def entry_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry's options, with each option the entry does not hold at its default."""
    return {**DEFAULT_OPTIONS, **entry.options}
