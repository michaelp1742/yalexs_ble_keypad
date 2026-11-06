"""Models for the Yale Access Bluetooth Keypad integration."""

from dataclasses import dataclass

from yalexs_ble import PushLock

from homeassistant.config_entries import ConfigEntry

from .store import PinStore


@dataclass(kw_only=True)
class YaleXSBLEKeypadData:
    """The runtime data of an entry: its title, its address, core's PushLock for the lock, and its PIN store."""

    title: str
    address: str
    lock: PushLock
    pins: PinStore


type YaleXSBLEKeypadConfigEntry = ConfigEntry[YaleXSBLEKeypadData]
