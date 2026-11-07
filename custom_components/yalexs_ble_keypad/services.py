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

from .cloud import CloudPin, LockPinParameters, lock_pin_parameters
from .const import (
    CONF_STATUS_RESULT,
    CREDENTIAL_TYPE_PIN,
    DOMAIN,
    MAX_SLOT,
    OWNER_DOMAIN,
    PIN_PATTERN,
    YaleXSBLEKeypadService,
    YaleXSBLEKeypadServiceArgument,
)
from .models import YaleXSBLEKeypadConfigEntry, entry_options
from .store import StoredPin

_LOGGER = logging.getLogger(__name__)

# The steps of a set that follow its Clear, so a refusal at one leaves the slot empty.
_SET_STEPS_AFTER_CLEAR = frozenset(
    {"set_keycode", "set_keycode_access", "commit_keycode"}
)

_REFUSAL_KEYS: dict[OperationError | int, str] = {
    OperationError.KEYCODE_EXISTING_KEY: "pin_already_in_use",
    OperationError.KEYCODE_NOSPACE: "keycode_no_space",
    OperationError.KEYCODE_TIMEOUT: "keycode_timeout",
    OperationError.KEYCODE_SLOT_IN_USE: "keycode_slot_in_use",
}

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
        if err.command in _SET_STEPS_AFTER_CLEAR and (
            key := _REFUSAL_KEYS.get(err.error)
        ):
            error_type = (
                ServiceValidationError
                if key == "pin_already_in_use"
                else HomeAssistantError
            )
            raise error_type(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={"step": err.command},
            ) from err
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="keycode_error",
            translation_placeholders={"error": str(err)},
        ) from err
    except ValueError as err:
        _LOGGER.debug("Keycode operation failed: %s", type(err).__name__)
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


def _check_keypad(parameters: LockPinParameters) -> None:
    """Raise when the lock's cloud record shows no keypad."""
    if parameters.has_keypad is False:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_keypad"
        )


def _check_slot(slot: int, parameters: LockPinParameters) -> None:
    """Raise when the slot is outside the lock's range of PIN slots."""
    if not parameters.pin_slot_min <= slot <= parameters.pin_slot_max:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_slot",
            translation_placeholders={
                "min": str(parameters.pin_slot_min),
                "max": str(parameters.pin_slot_max),
            },
        )


def _check_not_master_code_slot(slot: int, parameters: LockPinParameters) -> None:
    """Raise when the slot is the master code's, which the set and clear actions do not write or clear."""
    if slot == parameters.master_pin_slot:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="master_code_slot",
            translation_placeholders={"slot": str(slot)},
        )


def _check_pin(pin: str, parameters: LockPinParameters) -> None:
    """Raise when the PIN is not all digits, or its length is outside the parameters' range."""
    if (
        PIN_PATTERN.fullmatch(pin)
        and parameters.pin_length_min <= len(pin) <= parameters.pin_length_max
    ):
        return
    if parameters.pin_length_min == parameters.pin_length_max:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_pin_length",
            translation_placeholders={"length": str(parameters.pin_length_min)},
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_pin",
        translation_placeholders={
            "min": str(parameters.pin_length_min),
            "max": str(parameters.pin_length_max),
        },
    )


def _slot_holding_pin(
    pin: str,
    slot: int,
    kept_pins: Mapping[int, StoredPin],
    cloud_pins: tuple[CloudPin, ...],
) -> int | None:
    """Return the slot that holds the PIN: a stored slot other than the target, or any slot of the cloud record."""
    for kept_slot, stored in kept_pins.items():
        if kept_slot != slot and stored.pin == pin:
            return kept_slot
    for cloud_pin in cloud_pins:
        if cloud_pin.pin == pin:
            return cloud_pin.slot
    return None


async def _async_set_credential(
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry, data: Mapping[str, Any]
) -> None:
    """Set a keypad PIN on the entry's lock."""
    parameters = lock_pin_parameters(hass, entry.runtime_data.address)
    _check_keypad(parameters)
    slot: int = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX]
    _check_slot(slot, parameters)
    _check_not_master_code_slot(slot, parameters)
    pin: str = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_DATA]
    _check_pin(pin, parameters)
    pins = entry.runtime_data.pins
    if (
        used_slot := _slot_holding_pin(pin, slot, pins.pins(), parameters.cloud_pins)
    ) is not None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="pin_in_use",
            translation_placeholders={"slot": str(used_slot)},
        )
    # Every state counts: the lock holds the PIN of each entry but a created
    # one until the app's next sync acts on it, and a created entry is loaded
    # at that sync.
    if any(cloud_pin.slot == slot for cloud_pin in parameters.cloud_pins):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="slot_in_use",
            translation_placeholders={"slot": str(slot)},
        )
    with _translate_keycode_errors():
        held = await entry.runtime_data.lock.get_keycode(slot)
    if (kept := pins.get(slot)) is None:
        if held is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="slot_not_empty",
                translation_placeholders={"slot": str(slot)},
            )
    # The PIN being set passes, so that a set retried after one that stopped
    # partway is not refused for its own PIN.
    elif held not in (None, kept.pin, pin):
        await pins.async_remove(slot)
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="slot_holds_other_pin",
            translation_placeholders={"slot": str(slot)},
        )
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
    await pins.async_set(
        slot,
        StoredPin(pin=pin, name=data.get(YaleXSBLEKeypadServiceArgument.NAME) or None),
    )


async def _async_clear_credential(
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry, data: Mapping[str, Any]
) -> None:
    """Clear a keypad PIN on the entry's lock."""
    parameters = lock_pin_parameters(hass, entry.runtime_data.address)
    _check_keypad(parameters)
    slot: int = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX]
    _check_slot(slot, parameters)
    _check_not_master_code_slot(slot, parameters)
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
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry, data: Mapping[str, Any]
) -> dict[str, bool | str | None]:
    """Read a keypad PIN slot from the entry's lock."""
    parameters = lock_pin_parameters(hass, entry.runtime_data.address)
    _check_keypad(parameters)
    slot: int = data[YaleXSBLEKeypadServiceArgument.CREDENTIAL_INDEX]
    _check_slot(slot, parameters)
    if entry_options(entry)[CONF_STATUS_RESULT]:
        return await _async_slot_result(entry, slot)
    with _translate_keycode_errors():
        exists = await entry.runtime_data.lock.get_keycode(slot) is not None
    stored = entry.runtime_data.pins.get(slot) if exists else None
    return {
        "credential_exists": exists,
        "name": stored.name if stored else None,
    }


async def _async_slot_result(
    entry: YaleXSBLEKeypadConfigEntry, slot: int
) -> dict[str, bool | str | None]:
    """Read a keypad PIN slot and return its result.

    A refusal, a malformed PIN field, or no answer is a result, not an error.
    """
    exists: bool | None = None
    with _translate_keycode_errors():
        try:
            pin = await entry.runtime_data.lock.get_keycode(slot)
        except KeycodeError as err:
            result = (
                err.error.name
                if isinstance(err.error, OperationError)
                else f"0x{err.error:02X}"
            )
        except ValueError:
            result = "malformed"
        except TimeoutError:
            result = "timeout"
        else:
            exists = pin is not None
            result = "pin" if exists else "empty"
    _LOGGER.debug("Status read of slot %s: %s", slot, result)
    stored = entry.runtime_data.pins.get(slot) if exists else None
    return {
        "credential_exists": exists,
        "name": stored.name if stored else None,
        "result": result,
    }


async def async_set_lock_credential(call: ServiceCall) -> None:
    """Set a keypad PIN in a slot of each targeted lock."""
    hass = call.hass
    for entry_id in _async_target_entries(hass, call):
        await _async_set_credential(
            hass, hass.config_entries.async_get_known_entry(entry_id), call.data
        )


async def async_clear_lock_credential(call: ServiceCall) -> None:
    """Clear a keypad PIN slot of each targeted lock."""
    hass = call.hass
    for entry_id in _async_target_entries(hass, call):
        await _async_clear_credential(
            hass, hass.config_entries.async_get_known_entry(entry_id), call.data
        )


async def async_get_lock_credential_status(call: ServiceCall) -> ServiceResponse:
    """Return whether a keypad PIN slot of each targeted lock is in use, never the PIN itself."""
    hass = call.hass
    response: dict[str, Any] = {}
    for entry_id, entity_ids in _async_target_entries(hass, call).items():
        status = await _async_credential_status(
            hass, hass.config_entries.async_get_known_entry(entry_id), call.data
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
