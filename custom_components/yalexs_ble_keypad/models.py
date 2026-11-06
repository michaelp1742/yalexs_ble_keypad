"""Models for the Yale Access Bluetooth Keypad integration."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from yalexs_ble import PushLock

from homeassistant.config_entries import ConfigEntry

from .store import CredentialNames


@dataclass(kw_only=True)
class YaleXSBLEKeypadData:
    """The runtime data of an entry: its title, its address, and core's PushLock for the lock."""

    title: str
    address: str
    lock: PushLock
    credential_names: CredentialNames
    credential_operations: dict[
        tuple[str, str, tuple[tuple[str, Any], ...]], asyncio.Task[Any]
    ] = field(default_factory=dict)


type YaleXSBLEKeypadConfigEntry = ConfigEntry[YaleXSBLEKeypadData]
