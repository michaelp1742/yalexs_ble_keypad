"""The lock's PIN parameters from its cloud record, as a loaded yale entry holds it."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

from .const import CLOUD_DOMAIN

if TYPE_CHECKING:
    from yalexs.lock import LockDetail


@dataclass(frozen=True, kw_only=True)
class CloudPin:
    """An entry of the pins block of the lock's cloud record."""

    slot: int
    pin: str
    state: str


@dataclass(frozen=True, kw_only=True)
class LockPinParameters:
    """The lock's PIN parameters from its cloud record, and whether a record was found."""

    record_read: bool
    cloud_pins: tuple[CloudPin, ...]


@callback
def async_cloud_lock_detail(hass: HomeAssistant, address: str) -> LockDetail | None:
    """Return the cloud record of the lock at the address from a loaded yale entry."""
    for entry in hass.config_entries.async_loaded_entries(CLOUD_DOMAIN):
        data = entry.runtime_data
        for lock in data.locks:
            detail = data.get_device_detail(lock.device_id)
            if detail.mac_address == address:
                return detail
    return None


@callback
def lock_pin_parameters(hass: HomeAssistant, address: str) -> LockPinParameters:
    """Return the PIN parameters of the lock at the address, read from its cloud record on each call."""
    if (detail := async_cloud_lock_detail(hass, address)) is None:
        return LockPinParameters(record_read=False, cloud_pins=())
    return LockPinParameters(
        record_read=True,
        cloud_pins=tuple(
            CloudPin(slot=int(entry["slot"]), pin=entry["pin"], state=state)
            for state, entries in detail.raw.get("pins", {}).items()
            for entry in entries
        ),
    )
