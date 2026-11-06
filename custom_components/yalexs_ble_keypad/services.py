"""Services for Yale Access Bluetooth locks."""

import asyncio
from collections.abc import Callable, Coroutine, Generator
from contextlib import contextmanager
from functools import partial
import logging
import re
from typing import Any

from bleak.exc import BleakError
import probatio
from yalexs_ble import KeycodeError, OperationError, YaleXSBLEError

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import (
    Context,
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

from .const import (
    CREDENTIAL_TYPE_PIN,
    DOMAIN,
    MAX_PIN_SLOT,
    MIN_PIN_SLOT,
    OWNER_DOMAIN,
    YaleXSBLEService,
    YaleXSBLEServiceArgument,
)
from .models import YaleXSBLEKeypadConfigEntry

_LOGGER = logging.getLogger(__name__)

PIN_PATTERN = re.compile(r"[0-9]{4,8}")

_CREDENTIAL_TYPE = probatio.Required(YaleXSBLEServiceArgument.CREDENTIAL_TYPE)
_CREDENTIAL_INDEX = probatio.Required(YaleXSBLEServiceArgument.CREDENTIAL_INDEX)


def _slot() -> probatio.All:
    """Return a validator for a keypad PIN slot."""
    return probatio.All(
        probatio.Coerce(int), probatio.Range(min=MIN_PIN_SLOT, max=MAX_PIN_SLOT)
    )


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


class YaleXSBLEKeypadLock:
    """The keypad PIN actions of one lock entity of core's yalexs_ble, for one call."""

    def __init__(
        self, hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry, context: Context
    ) -> None:
        """Initialize the actions with the entry of the entity's lock."""
        self.hass = hass
        self._entry = entry
        self._data = entry.runtime_data
        self._device = entry.runtime_data.lock
        self._context: Context | None = context
        self._context_set: float | None = None

    async def _async_run_once[T](
        self,
        name: str,
        data: dict[str, Any],
        operation: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        """Run a credential operation once per service call across sibling entities."""
        assert self._context is not None
        # A context spans a script run, so parallel calls need the data to tell apart.
        key = (name, self._context.id, tuple(sorted(data.items())))
        # The action never changes state, so keep its context off later writes,
        # including those from lock actions that run while it is in progress.
        self._context = None
        self._context_set = None
        operations = self._data.credential_operations
        if (task := operations.get(key)) is None:
            config_entry = self._entry
            assert config_entry is not None
            # Cancelled on unload, which always precedes removing the stored names.
            task = config_entry.async_create_background_task(
                self.hass, operation(), f"{DOMAIN} credential {name}"
            )
            operations[key] = task
            task.add_done_callback(lambda _: operations.pop(key, None))
        result: T = await task
        return result

    async def async_set_lock_credential(self, **kwargs: Any) -> None:
        """Set a keypad PIN."""
        await self._async_run_once(
            "set", kwargs, lambda: self._set_credential(**kwargs)
        )

    async def _set_credential(self, **kwargs: Any) -> None:
        """Set a keypad PIN on the lock."""
        pin: str = kwargs[YaleXSBLEServiceArgument.CREDENTIAL_DATA]
        if not PIN_PATTERN.fullmatch(pin):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_pin"
            )
        slot: int = kwargs[YaleXSBLEServiceArgument.CREDENTIAL_INDEX]
        try:
            with _translate_keycode_errors():
                await self._device.set_keycode(slot, pin)
        except HomeAssistantError as err:
            if not _keycode_slot_unchanged(err.__cause__):
                await self._data.credential_names.async_remove(slot)
            raise
        except asyncio.CancelledError:
            # Programming may have started, so the old label might be wrong.
            await self._data.credential_names.async_remove(slot)
            raise
        if name := kwargs.get(YaleXSBLEServiceArgument.NAME):
            await self._data.credential_names.async_set(slot, name)

    async def async_clear_lock_credential(self, **kwargs: Any) -> None:
        """Clear a keypad PIN."""
        await self._async_run_once(
            "clear", kwargs, lambda: self._clear_credential(**kwargs)
        )

    async def _clear_credential(self, **kwargs: Any) -> None:
        """Clear a keypad PIN on the lock."""
        slot: int = kwargs[YaleXSBLEServiceArgument.CREDENTIAL_INDEX]
        try:
            with _translate_keycode_errors():
                await self._device.clear_keycode(slot)
        except HomeAssistantError as err:
            if not _keycode_slot_unchanged(err.__cause__):
                await self._data.credential_names.async_remove(slot)
            raise
        except asyncio.CancelledError:
            # The PIN may already be gone, so the old label might be wrong.
            await self._data.credential_names.async_remove(slot)
            raise
        await self._data.credential_names.async_remove(slot)

    async def async_get_lock_credential_status(
        self, **kwargs: Any
    ) -> dict[str, bool | str | None]:
        """Return whether a keypad PIN slot is in use, never the PIN itself."""
        return await self._async_run_once(
            "status", kwargs, lambda: self._credential_status(**kwargs)
        )

    async def _credential_status(self, **kwargs: Any) -> dict[str, bool | str | None]:
        """Read a keypad PIN slot from the lock."""
        slot: int = kwargs[YaleXSBLEServiceArgument.CREDENTIAL_INDEX]
        with _translate_keycode_errors():
            exists = await self._device.get_keycode(slot) is not None
        return {
            "credential_exists": exists,
            "name": self._data.credential_names.get(slot) if exists else None,
        }


async def _async_call_locks(func: str, call: ServiceCall) -> ServiceResponse:
    """Run an action on each targeted lock entity of core's yalexs_ble whose lock has an entry."""
    hass = call.hass
    entity_registry = er.async_get(hass)
    entries: dict[str, YaleXSBLEKeypadConfigEntry] = {
        entry.data[CONF_ADDRESS]: entry
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    }
    locks: dict[str, YaleXSBLEKeypadLock] = {}
    for entity_id in await service.async_extract_entity_ids(call):
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
            or (entry := entries.get(owner.data[CONF_ADDRESS])) is None
        ):
            continue
        locks[entity_id] = YaleXSBLEKeypadLock(hass, entry, call.context)
    data = service.remove_entity_service_fields(call)
    results = await asyncio.gather(
        *(getattr(lock, func)(**data) for lock in locks.values())
    )
    if not call.return_response:
        return None
    return dict(zip(locks, results, strict=True))


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Yale Access Bluetooth services."""
    service.async_register_admin_service(
        hass,
        DOMAIN,
        YaleXSBLEService.SET_LOCK_CREDENTIAL,
        partial(_async_call_locks, "async_set_lock_credential"),
        cv.make_entity_service_schema(
            {
                _CREDENTIAL_TYPE: probatio.In([CREDENTIAL_TYPE_PIN]),
                probatio.Required(YaleXSBLEServiceArgument.CREDENTIAL_DATA): cv.string,
                _CREDENTIAL_INDEX: _slot(),
                probatio.Optional(YaleXSBLEServiceArgument.NAME): cv.string,
            }
        ),
    )

    service.async_register_admin_service(
        hass,
        DOMAIN,
        YaleXSBLEService.CLEAR_LOCK_CREDENTIAL,
        partial(_async_call_locks, "async_clear_lock_credential"),
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
        YaleXSBLEService.GET_LOCK_CREDENTIAL_STATUS,
        partial(_async_call_locks, "async_get_lock_credential_status"),
        cv.make_entity_service_schema(
            {
                _CREDENTIAL_TYPE: probatio.In([CREDENTIAL_TYPE_PIN]),
                _CREDENTIAL_INDEX: _slot(),
            }
        ),
        SupportsResponse.ONLY,
    )
