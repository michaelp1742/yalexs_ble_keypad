"""The keypad PIN actions of the Yale Access Bluetooth Keypad integration."""

import asyncio
from collections.abc import Generator, Mapping
from contextlib import contextmanager
import logging
from typing import Any

from bleak.exc import BleakError
import probatio
from yalexs_ble import KeycodeError, OperationError, YaleXSBLEError

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    service,
)
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)

from .const import (
    CREDENTIAL_TYPE_PIN,
    DOMAIN,
    MAX_PIN_SLOT,
    MAX_SLOT,
    MIN_PIN_SLOT,
    OWNER_DOMAIN,
    PIN_PATTERN,
    YaleXSBLEKeypadService,
    YaleXSBLEKeypadServiceArgument,
)
from .models import YaleXSBLEKeypadConfigEntry
from .store import StoredPin

_LOGGER = logging.getLogger(__name__)

_CREDENTIAL_TYPE = probatio.Required(YaleXSBLEKeypadServiceArgument.CREDENTIAL_TYPE)
_CREDENTIAL_INDEX = probatio.Required(YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX)


def _slot() -> probatio.All:
    """Return a validator for the slot field."""
    return probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=MAX_SLOT))


def _keycode_slot_unchanged(err: BaseException | None) -> bool:
    """Return if a failed set left the slot as it was.

    That is when only the clear step failed, or the lock was not running so
    nothing was sent.
    """
    return isinstance(err, RuntimeError) or (
        isinstance(err, KeycodeError) and err.command == "clear_keycode"
    )


@contextmanager
def _translate_keycode_errors() -> Generator[None]:
    """Translate library errors from keycode operations."""
    try:
        yield
    except KeycodeError as err:
        if err.error is OperationError.KEYCODE_EXISTING_KEY:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="pin_already_in_use"
            ) from err
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="keycode_error",
            translation_placeholders={"error": str(err)},
        ) from err
    except ValueError:
        # The library's message carries the raw PIN bytes of a malformed read.
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="invalid_response"
        ) from None
    except (YaleXSBLEError, BleakError, EOFError, OSError, TimeoutError) as err:
        # Library messages can include decrypted frames, which hold the PIN.
        _LOGGER.debug("Keycode operation failed: %s", type(err).__name__)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="communication_error"
        ) from None
    except RuntimeError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="lock_not_running",
        ) from err


@callback
def _async_target_entries(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, list[str]]:
    """Return the ids of the entries of the targeted locks, each with the lock entity ids that reached it."""
    entity_registry = er.async_get(hass)
    entries: dict[str, YaleXSBLEKeypadConfigEntry] = {
        entry.data[CONF_ADDRESS]: entry
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    }
    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    targets: dict[str, list[str]] = {}
    for entity_id in sorted(selected.referenced | selected.indirectly_referenced):
        if (
            (registry_entry := entity_registry.async_get(entity_id)) is None
            or registry_entry.domain != LOCK_DOMAIN
            or registry_entry.platform != OWNER_DOMAIN
            or registry_entry.config_entry_id is None
            or (
                owner := hass.config_entries.async_get_entry(
                    registry_entry.config_entry_id
                )
            )
            is None
        ):
            continue
        if (entry := entries.get(owner.data[CONF_ADDRESS])) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="lock_not_configured",
                translation_placeholders={"entity_id": entity_id},
            )
        targets.setdefault(entry.entry_id, []).append(entity_id)
    if not targets:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_lock_targeted"
        )
    return targets


def _check_slot(slot: int) -> None:
    """Raise when the slot is outside the range of PIN slots."""
    if not MIN_PIN_SLOT <= slot <= MAX_PIN_SLOT:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_slot",
            translation_placeholders={
                "min": str(MIN_PIN_SLOT),
                "max": str(MAX_PIN_SLOT),
            },
        )


async def _async_set_credential(
    entry: YaleXSBLEKeypadConfigEntry, data: Mapping[str, Any]
) -> None:
    """Set a keypad PIN on the entry's lock."""
    slot: int = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX]
    _check_slot(slot)
    pin: str = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_DATA]
    if not PIN_PATTERN.fullmatch(pin):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_pin"
        )
    pins = entry.runtime_data.pins
    try:
        with _translate_keycode_errors():
            await entry.runtime_data.lock.set_keycode(slot, pin)
    except HomeAssistantError as err:
        if not _keycode_slot_unchanged(err.__cause__):
            await pins.async_remove(slot)
        raise
    except asyncio.CancelledError:
        # Programming may have started, so the slot's record might be wrong.
        await pins.async_remove(slot)
        raise
    if not (name := data.get(YaleXSBLEKeypadServiceArgument.NAME)) and (
        stored := pins.get(slot)
    ):
        name = stored.name
    await pins.async_set(slot, StoredPin(pin=pin, name=name))


async def _async_clear_credential(
    entry: YaleXSBLEKeypadConfigEntry, data: Mapping[str, Any]
) -> None:
    """Clear a keypad PIN on the entry's lock."""
    slot: int = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX]
    _check_slot(slot)
    pins = entry.runtime_data.pins
    try:
        with _translate_keycode_errors():
            await entry.runtime_data.lock.clear_keycode(slot)
    except HomeAssistantError as err:
        if not _keycode_slot_unchanged(err.__cause__):
            await pins.async_remove(slot)
        raise
    except asyncio.CancelledError:
        # The PIN may already be gone, so the slot's record might be wrong.
        await pins.async_remove(slot)
        raise
    await pins.async_remove(slot)


async def _async_credential_status(
    entry: YaleXSBLEKeypadConfigEntry, data: Mapping[str, Any]
) -> dict[str, bool | str | None]:
    """Read a keypad PIN slot from the entry's lock."""
    slot: int = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX]
    _check_slot(slot)
    with _translate_keycode_errors():
        exists = await entry.runtime_data.lock.get_keycode(slot) is not None
    stored = entry.runtime_data.pins.get(slot) if exists else None
    return {
        "credential_exists": exists,
        "name": stored.name if stored else None,
    }


async def async_set_lock_credential(call: ServiceCall) -> None:
    """Set a keypad PIN in a slot of each targeted lock."""
    hass = call.hass
    for entry_id in _async_target_entries(hass, call):
        await _async_set_credential(
            hass.config_entries.async_get_known_entry(entry_id), call.data
        )


async def async_clear_lock_credential(call: ServiceCall) -> None:
    """Clear a keypad PIN slot of each targeted lock."""
    hass = call.hass
    for entry_id in _async_target_entries(hass, call):
        await _async_clear_credential(
            hass.config_entries.async_get_known_entry(entry_id), call.data
        )


async def async_get_lock_credential_status(call: ServiceCall) -> ServiceResponse:
    """Return whether a keypad PIN slot of each targeted lock is in use, never the PIN itself."""
    hass = call.hass
    response: dict[str, Any] = {}
    for entry_id, entity_ids in _async_target_entries(hass, call).items():
        status = await _async_credential_status(
            hass.config_entries.async_get_known_entry(entry_id), call.data
        )
        response.update(dict.fromkeys(entity_ids, status))
    return response


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the keypad PIN actions."""
    service.async_register_admin_service(
        hass,
        DOMAIN,
        YaleXSBLEKeypadService.SET_LOCK_CREDENTIAL,
        async_set_lock_credential,
        cv.make_entity_service_schema(
            {
                _CREDENTIAL_TYPE: probatio.In([CREDENTIAL_TYPE_PIN]),
                probatio.Required(
                    YaleXSBLEKeypadServiceArgument.CREDENTIAL_DATA
                ): cv.string,
                _CREDENTIAL_INDEX: _slot(),
                probatio.Optional(YaleXSBLEKeypadServiceArgument.NAME): cv.string,
            }
        ),
    )

    service.async_register_admin_service(
        hass,
        DOMAIN,
        YaleXSBLEKeypadService.CLEAR_LOCK_CREDENTIAL,
        async_clear_lock_credential,
        cv.make_entity_service_schema(
            {
                _CREDENTIAL_TYPE: probatio.In([CREDENTIAL_TYPE_PIN]),
                _CREDENTIAL_INDEX: _slot(),
            }
        ),
    )

    service.async_register_admin_service(
        hass,
        DOMAIN,
        YaleXSBLEKeypadService.GET_LOCK_CREDENTIAL_STATUS,
        async_get_lock_credential_status,
        cv.make_entity_service_schema(
            {
                _CREDENTIAL_TYPE: probatio.In([CREDENTIAL_TYPE_PIN]),
                _CREDENTIAL_INDEX: _slot(),
            }
        ),
        SupportsResponse.ONLY,
    )
