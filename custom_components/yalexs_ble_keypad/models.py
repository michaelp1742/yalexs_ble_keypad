"""Models for the Yale Access Bluetooth Keypad integration."""

from dataclasses import dataclass

from yalexs_ble import PushLock

from homeassistant.config_entries import ConfigEntry


@dataclass(kw_only=True)
class YaleXSBLEKeypadData:
    """The runtime data of an entry: its title, its address, and core's PushLock for the lock."""

    title: str
    address: str
    lock: PushLock


type YaleXSBLEKeypadConfigEntry = ConfigEntry[YaleXSBLEKeypadData]
