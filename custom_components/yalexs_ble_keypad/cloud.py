"""The lock's PIN parameters from its cloud record, as a loaded yale entry holds it."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback

from .const import (
    CLOUD_DOMAIN,
    CONF_CLOUD_PIN_RULES,
    DEFAULT_PIN_LENGTH,
    MASTER_CODE_SLOT,
    MAX_PIN_LENGTH,
    MAX_PIN_SLOT,
    MIN_PIN_LENGTH,
    MIN_PIN_SLOT,
)

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
    has_keypad: bool | None
    pin_length_min: int
    pin_length_max: int
    pin_slot_min: int
    pin_slot_max: int
    master_pin_slot: int | None
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


def _lock_capabilities(detail: LockDetail) -> dict[str, Any] | None:
    """Return the lock block of the record's capabilities, or None when the record has no capabilities."""
    # A yalexs that does not fetch the capabilities has no capabilities property on LockDetail.
    if (capabilities := getattr(detail, "capabilities", None)) is None:
        return None
    block = capabilities.get("lock")
    return block if isinstance(block, dict) else {}


def _pin_length_range(capabilities: Mapping[str, Any]) -> tuple[int, int]:
    """Return the shortest and longest PIN length the capabilities allow."""
    if "pinLengthMin" in capabilities and "pinLengthMax" in capabilities:
        return int(capabilities["pinLengthMin"]), int(capabilities["pinLengthMax"])
    if "pinLength" in capabilities:
        return int(capabilities["pinLength"]), int(capabilities["pinLength"])
    return DEFAULT_PIN_LENGTH, DEFAULT_PIN_LENGTH


def _pin_slot_range(capabilities: Mapping[str, Any]) -> tuple[int, int]:
    """Return the lowest and highest PIN slot the capabilities give, else the constants."""
    if isinstance(low := capabilities.get("pinSlotMin"), int) and isinstance(
        high := capabilities.get("pinSlotMax"), int
    ):
        return low, high
    return MIN_PIN_SLOT, MAX_PIN_SLOT


@callback
def lock_pin_parameters(
    hass: HomeAssistant, address: str, options: Mapping[str, Any]
) -> LockPinParameters:
    """Return the PIN parameters of the lock at the address, read from its cloud record on each call."""
    detail = async_cloud_lock_detail(hass, address)
    capabilities = None if detail is None else _lock_capabilities(detail)
    has_keypad: bool | None = None
    pin_length_min, pin_length_max = MIN_PIN_LENGTH, MAX_PIN_LENGTH
    pin_slot_min, pin_slot_max = MIN_PIN_SLOT, MAX_PIN_SLOT
    master_pin_slot: int | None = MASTER_CODE_SLOT
    if (
        options[CONF_CLOUD_PIN_RULES]
        and detail is not None
        and capabilities is not None
    ):
        has_keypad = (
            detail.keypad is not None or capabilities.get("integratedKeypad") is True
        )
        pin_length_min, pin_length_max = _pin_length_range(capabilities)
        master_pin_slot = (
            slot
            if isinstance(slot := capabilities.get("masterPinSlot"), int) and slot > 0
            else None
        )
    if capabilities is not None:
        pin_slot_min, pin_slot_max = _pin_slot_range(capabilities)
    return LockPinParameters(
        record_read=detail is not None,
        has_keypad=has_keypad,
        pin_length_min=pin_length_min,
        pin_length_max=pin_length_max,
        pin_slot_min=pin_slot_min,
        pin_slot_max=pin_slot_max,
        master_pin_slot=master_pin_slot,
        cloud_pins=()
        if detail is None
        else tuple(
            CloudPin(slot=int(entry["slot"]), pin=entry["pin"], state=state)
            for state, entries in detail.raw.get("pins", {}).items()
            for entry in entries
        ),
    )
