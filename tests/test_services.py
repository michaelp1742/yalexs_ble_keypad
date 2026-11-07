"""Test the Yale Access Bluetooth lock credential services."""

import asyncio
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakDBusError, BleakError
from bleak_retry_connector import BleakNotFoundError, BleakOutOfConnectionSlotsError
import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from yalexs_ble import KeycodeError, YaleXSBLEError
from yalexs_ble.const import OperationError
from yalexs_ble.session import ResponseError

from custom_components.yalexs_ble_keypad.const import DOMAIN, OWNER_DOMAIN
from custom_components.yalexs_ble_keypad.store import PinStore
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from . import ADDRESS, TITLE, async_setup_cloud, async_setup_owner, cloud_record

ENTITY_ID = "lock.front_door"
SECURE_ENTITY_ID = "lock.front_door_secure_mode"
STORAGE_KEY = "yalexs_ble_keypad.{}.pins"
GUEST = {"3": {"pin": "4321", "name": "Guest"}}

# A constructed cloud record of the Front Door with a keypad block, and the capabilities a test reads for it.
FRONT_DOOR_RECORD = cloud_record(
    "front",
    ADDRESS,
    keypad={
        "_id": "keypad",
        "serialNumber": "keypad-serial",
        "currentFirmwareVersion": "1.0.0",
        "batteryLevel": "Full",
    },
)
FRONT_DOOR_CAPABILITIES = {
    "lock": {"pinLength": 6, "masterPinSlot": 65518, "pinSlotMin": 1, "pinSlotMax": 100}
}


class MockLock:
    """Holder for the mocked PushLock."""

    def __init__(self) -> None:
        """Initialize the mock."""
        self.push_lock = MagicMock()
        self.push_lock.address = ADDRESS
        self.push_lock.get_keycode = AsyncMock(return_value=None)
        self.push_lock.set_keycode = AsyncMock()
        self.push_lock.clear_keycode = AsyncMock()


@pytest.fixture
def mock_lock() -> MockLock:
    """Return a mocked lock."""
    return MockLock()


@pytest.fixture
def options() -> dict[str, Any]:
    """Return the keypad entry's options: none, so each option takes its default."""
    return {}


@pytest.fixture
async def entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    mock_lock: MockLock,
    options: dict[str, Any],
) -> MockConfigEntry:
    """Set up a keypad entry on core's entry with a mocked lock and its two lock entities."""
    owner = await async_setup_owner(hass)
    owner.runtime_data.lock = mock_lock.push_lock
    device = device_registry.async_get_or_create(
        config_entry_id=owner.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
    )
    for unique_id, object_id in (
        (ADDRESS, "front_door"),
        (f"{ADDRESS}_secure_mode", "front_door_secure_mode"),
    ):
        entity_registry.async_get_or_create(
            LOCK_DOMAIN,
            OWNER_DOMAIN,
            unique_id,
            suggested_object_id=object_id,
            config_entry=owner,
            device_id=device.id,
        )
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        data={CONF_ADDRESS: ADDRESS},
        options=options,
        unique_id=ADDRESS,
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


def _stored_pins(
    hass_storage: dict[str, Any], entry: MockConfigEntry
) -> dict[str, dict[str, str | None]]:
    """Return the PINs in the entry's store file."""
    return hass_storage[STORAGE_KEY.format(entry.entry_id)]["data"]["pins"]


async def _set_guest(hass: HomeAssistant) -> None:
    """Store PIN 4321 named Guest at slot 3 through the set action."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "4321", "credential_index": 3, "name": "Guest"},
    )


def _call(
    hass: HomeAssistant, service: str, data: dict[str, Any], **kwargs: Any
) -> Any:
    """Call a yalexs_ble lock service."""
    return hass.services.async_call(
        DOMAIN,
        service,
        {"entity_id": ENTITY_ID, "credential_type": "pin", **data},
        blocking=True,
        **kwargs,
    )


@pytest.mark.usefixtures("entry")
async def test_set_credential_stores_pin_and_name(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test setting a PIN with a name stores both for the slot."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "1234", "credential_index": 205, "name": "Jesse"},
    )

    mock_lock.push_lock.set_keycode.assert_awaited_once_with(205, "1234")
    assert _stored_pins(hass_storage, entry) == {
        "205": {"pin": "1234", "name": "Jesse"}
    }


async def test_reload_keeps_stored_pins(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test the stored PINs survive a reload, with the store file unchanged."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "1234", "credential_index": 12, "name": "Cleaner"},
    )
    stored = deepcopy(hass_storage[STORAGE_KEY.format(entry.entry_id)])

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    mock_lock.push_lock.get_keycode.return_value = "1234"
    response = await _call(
        hass,
        "get_lock_credential_status",
        {"credential_index": 12},
        return_response=True,
    )

    assert entry.state is ConfigEntryState.LOADED
    assert response == {
        ENTITY_ID: {
            "credential_exists": True,
            "name": "Cleaner",
            "result": "pin",
            "pin": "1234",
        }
    }
    assert hass_storage[STORAGE_KEY.format(entry.entry_id)] == stored


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "name_field",
    [
        pytest.param({}, id="absent"),
        pytest.param({"name": ""}, id="empty"),
    ],
)
async def test_set_credential_without_name_stores_no_name(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    name_field: dict[str, str],
) -> None:
    """Test a set with no name or an empty name at a named slot replaces the PIN and leaves the slot with no name."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "1234", "credential_index": 5, "name": "Guest"},
    )
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "5678", "credential_index": 5, **name_field},
    )
    mock_lock.push_lock.get_keycode.return_value = "5678"

    response = await _call(
        hass,
        "get_lock_credential_status",
        {"credential_index": 5},
        return_response=True,
    )

    assert _stored_pins(hass_storage, entry) == {"5": {"pin": "5678", "name": None}}
    assert response == {
        ENTITY_ID: {
            "credential_exists": True,
            "name": None,
            "result": "pin",
            "pin": "5678",
        }
    }


@pytest.mark.usefixtures("entry")
async def test_set_credential_empty_name_on_empty_slot_stores_no_name(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test an empty name on a slot with no record stores the PIN with no name."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "5678", "credential_index": 5, "name": ""},
    )
    mock_lock.push_lock.get_keycode.return_value = "5678"

    response = await _call(
        hass,
        "get_lock_credential_status",
        {"credential_index": 5},
        return_response=True,
    )

    assert _stored_pins(hass_storage, entry) == {"5": {"pin": "5678", "name": None}}
    assert response == {
        ENTITY_ID: {
            "credential_exists": True,
            "name": None,
            "result": "pin",
            "pin": "5678",
        }
    }


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "pin",
    ["123", "123456789", "12a4", "١٢٣٤"],
    ids=["short", "long", "alpha", "unicode"],
)
async def test_set_credential_invalid_pin(
    hass: HomeAssistant, mock_lock: MockLock, pin: str
) -> None:
    """Test an invalid PIN is rejected before talking to the lock."""
    with pytest.raises(ServiceValidationError, match="4 to 8 digits"):
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": pin, "credential_index": 1},
        )
    mock_lock.push_lock.set_keycode.assert_not_awaited()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("data", "exception"),
    [
        pytest.param({"credential_index": 0}, ServiceValidationError, id="slot_low"),
        pytest.param({"credential_index": 251}, ServiceValidationError, id="slot_high"),
        pytest.param(
            {"credential_index": 1, "credential_type": "rfid"},
            probatio.MultipleInvalid,
            id="type",
        ),
    ],
)
async def test_set_credential_rejects_slot_and_type_before_the_lock(
    hass: HomeAssistant,
    mock_lock: MockLock,
    data: dict[str, Any],
    exception: type[Exception],
) -> None:
    """Test a slot outside the PIN range or a credential type other than pin is refused and the lock is not called."""
    with pytest.raises(exception):
        await _call(hass, "set_lock_credential", {"credential_data": "1234", **data})
    mock_lock.push_lock.set_keycode.assert_not_awaited()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("error", "exception", "message"),
    [
        pytest.param(
            KeycodeError("commit_keycode", OperationError.KEYCODE_EXISTING_KEY),
            ServiceValidationError,
            "already exists on the lock",
            id="existing_key",
        ),
        pytest.param(
            KeycodeError("commit_keycode", OperationError.NACK),
            HomeAssistantError,
            "rejected the keypad request",
            id="keycode_error",
        ),
        pytest.param(
            YaleXSBLEError("boom"),
            HomeAssistantError,
            "Failed to communicate",
            id="ble_error",
        ),
        pytest.param(
            TimeoutError("slow"),
            HomeAssistantError,
            "Failed to communicate",
            id="timeout",
        ),
    ],
)
async def test_set_credential_errors(
    hass: HomeAssistant,
    mock_lock: MockLock,
    hass_storage: dict[str, Any],
    error: Exception,
    exception: type[Exception],
    message: str,
) -> None:
    """Test library errors are translated and no name is stored."""
    mock_lock.push_lock.set_keycode.side_effect = error
    with pytest.raises(exception, match=message):
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 3, "name": "Nope"},
        )
    assert not any(key.startswith("yalexs_ble_keypad.") for key in hass_storage)


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            KeycodeError("clear_keycode", OperationError.KEYCODE_NOSPACE),
            GUEST,
            id="clear_failed",
        ),
        pytest.param(
            KeycodeError("commit_keycode", OperationError.KEYCODE_NOSPACE),
            {},
            id="commit_failed",
        ),
        pytest.param(RuntimeError("not running"), GUEST, id="not_running"),
        pytest.param(BleakError("gone"), {}, id="bleak"),
    ],
)
async def test_failed_set_credential_record_handling(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    error: Exception,
    expected: dict[str, dict[str, str | None]],
) -> None:
    """Test a failed set keeps the slot's record only when the slot is unchanged."""
    await _set_guest(hass)
    mock_lock.push_lock.set_keycode.side_effect = error
    with pytest.raises(HomeAssistantError):
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 3},
        )
    assert _stored_pins(hass_storage, entry) == expected


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("method", "service", "data", "extra", "options"),
    [
        pytest.param(
            "set_keycode",
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 3},
            {},
            {},
            id="set",
        ),
        pytest.param(
            "clear_keycode",
            "clear_lock_credential",
            {"credential_index": 3},
            {},
            {},
            id="clear",
        ),
        pytest.param(
            "get_keycode",
            "get_lock_credential_status",
            {"credential_index": 3},
            {"return_response": True},
            {"status_result": False},
            id="status_answer_off",
        ),
    ],
)
@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        pytest.param(BleakError("gone"), "communication_error", id="bleak"),
        pytest.param(
            BleakDBusError("org.bluez.Error", []),
            "communication_error",
            id="bleak_dbus",
        ),
        pytest.param(
            BleakOutOfConnectionSlotsError("no slots"),
            "communication_error",
            id="no_slots",
        ),
        pytest.param(
            BleakNotFoundError("missing"), "communication_error", id="not_found"
        ),
        pytest.param(EOFError("eof"), "communication_error", id="eof"),
        pytest.param(BrokenPipeError("pipe"), "communication_error", id="broken_pipe"),
        pytest.param(RuntimeError("not running"), "lock_not_running", id="not_running"),
        pytest.param(
            ValueError("Malformed PIN field: 1234ffffff"),
            "invalid_response",
            id="malformed_pin",
        ),
        pytest.param(
            ResponseError("bad frame 1234ffffff"),
            "communication_error",
            id="response_error",
        ),
    ],
)
async def test_credential_services_translate_library_errors(
    hass: HomeAssistant,
    mock_lock: MockLock,
    method: str,
    service: str,
    data: dict[str, Any],
    extra: dict[str, Any],
    error: Exception,
    translation_key: str,
) -> None:
    """Test every escaping library error is translated by each service."""
    getattr(mock_lock.push_lock, method).side_effect = error
    with pytest.raises(HomeAssistantError) as exc_info:
        await _call(hass, service, data, **extra)
    assert exc_info.value.translation_key == translation_key
    assert exc_info.value.translation_placeholders in (None, {})
    assert "1234" not in str(exc_info.value)


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options", [pytest.param({"status_result": False}, id="status_answer_off")]
)
@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        pytest.param(
            ValueError("Malformed PIN field: 1234ffffff"),
            "invalid_response",
            id="malformed_pin",
        ),
        pytest.param(
            ResponseError("frame 1234ffffff"), "communication_error", id="response"
        ),
    ],
)
async def test_credential_errors_do_not_expose_pin_data(
    hass: HomeAssistant,
    mock_lock: MockLock,
    error: Exception,
    translation_key: str,
) -> None:
    """Test PIN bytes in library errors never reach the raised error."""
    mock_lock.push_lock.get_keycode.side_effect = error
    with pytest.raises(HomeAssistantError) as exc_info:
        await _call(
            hass,
            "get_lock_credential_status",
            {"credential_index": 3},
            return_response=True,
        )
    assert exc_info.value.translation_key == translation_key
    assert exc_info.value.translation_placeholders is None
    assert exc_info.value.__cause__ is None
    assert "1234" not in str(exc_info.value)


@pytest.mark.usefixtures("entry")
async def test_clear_credential_removes_name(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test clearing a slot removes its stored name."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "1234", "credential_index": 7, "name": "Cleaner"},
    )
    await _call(hass, "clear_lock_credential", {"credential_index": 7})

    mock_lock.push_lock.clear_keycode.assert_awaited_once_with(7)
    assert _stored_pins(hass_storage, entry) == {}


@pytest.mark.usefixtures("entry")
async def test_clear_credential_unnamed_slot(
    hass: HomeAssistant, mock_lock: MockLock, hass_storage: dict[str, Any]
) -> None:
    """Test clearing a slot without a stored name does not write storage."""
    await _call(hass, "clear_lock_credential", {"credential_index": 8})

    mock_lock.push_lock.clear_keycode.assert_awaited_once_with(8)
    assert not any(key.startswith("yalexs_ble_keypad.") for key in hass_storage)


@pytest.mark.usefixtures("entry")
async def test_clear_credential_error(hass: HomeAssistant, mock_lock: MockLock) -> None:
    """Test clear errors are translated."""
    mock_lock.push_lock.clear_keycode.side_effect = YaleXSBLEError("boom")
    with pytest.raises(HomeAssistantError, match="Failed to communicate"):
        await _call(hass, "clear_lock_credential", {"credential_index": 8})


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options", [pytest.param({"status_result": False}, id="status_answer_off")]
)
async def test_credential_status(hass: HomeAssistant, mock_lock: MockLock) -> None:
    """Test status with the status answer off reports existence and name but never the PIN."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "4321", "credential_index": 9, "name": "Nan"},
    )
    mock_lock.push_lock.get_keycode.return_value = "4321"

    response = await _call(
        hass,
        "get_lock_credential_status",
        {"credential_index": 9},
        return_response=True,
    )
    assert response == {
        ENTITY_ID: {"credential_exists": True, "name": "Nan"},
    }
    assert "4321" not in str(response)

    mock_lock.push_lock.get_keycode.return_value = None
    response = await _call(
        hass,
        "get_lock_credential_status",
        {"credential_index": 9},
        return_response=True,
    )
    assert response == {ENTITY_ID: {"credential_exists": False, "name": None}}


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options", [pytest.param({"status_result": False}, id="status_answer_off")]
)
async def test_credential_status_error(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """Test a failed status read with the status answer off raises its translated error."""
    mock_lock.push_lock.get_keycode.side_effect = KeycodeError(
        "get_keycode", OperationError.KEYCODE_TIMEOUT
    )
    with pytest.raises(
        HomeAssistantError, match="rejected the keypad request"
    ) as exc_info:
        await _call(
            hass,
            "get_lock_credential_status",
            {"credential_index": 9},
            return_response=True,
        )
    assert exc_info.value.translation_key == "keycode_error"


@pytest.mark.usefixtures("entry")
async def test_services_require_admin(
    hass: HomeAssistant, hass_read_only_user: MockUser
) -> None:
    """Test the credential services need an admin user."""
    with pytest.raises(Unauthorized):
        await _call(
            hass,
            "clear_lock_credential",
            {"credential_index": 1},
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_remove_deletes_store(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test removing the entry deletes its stored PINs."""
    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "1234", "credential_index": 2, "name": "Temp"},
    )
    key = STORAGE_KEY.format(entry.entry_id)
    assert key in hass_storage

    await hass.config_entries.async_unload(entry.entry_id)

    await hass.config_entries.async_remove(entry.entry_id)
    assert key not in hass_storage


def _call_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entry: MockConfigEntry,
    service: str,
    data: dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Call a yalexs_ble lock service targeting the whole device."""
    owner = hass.config_entries.async_entry_for_domain_unique_id(
        OWNER_DOMAIN, entry.unique_id
    )
    device = device_registry.async_get_device_by_connection(
        ("bluetooth", ADDRESS), owner.entry_id
    )
    return hass.services.async_call(
        DOMAIN,
        service,
        {"device_id": device.id, "credential_type": "pin", **data},
        blocking=True,
        **kwargs,
    )


async def test_device_target_set_credential_runs_once(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test targeting both lock entities sets the PIN and name once."""
    with patch.object(
        PinStore,
        "async_set",
        autospec=True,
        side_effect=PinStore.async_set,
    ) as name_set:
        await _call_device(
            hass,
            device_registry,
            entry,
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 5, "name": "Jesse"},
        )

    mock_lock.push_lock.set_keycode.assert_awaited_once_with(5, "1234")
    assert name_set.await_count == 1
    assert _stored_pins(hass_storage, entry) == {"5": {"pin": "1234", "name": "Jesse"}}


async def test_device_target_clear_credential_runs_once(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_lock: MockLock,
    entry: MockConfigEntry,
) -> None:
    """Test targeting both lock entities clears the PIN and name once."""
    with patch.object(
        PinStore,
        "async_remove",
        autospec=True,
        side_effect=PinStore.async_remove,
    ) as name_remove:
        await _call_device(
            hass,
            device_registry,
            entry,
            "clear_lock_credential",
            {"credential_index": 5},
        )

    mock_lock.push_lock.clear_keycode.assert_awaited_once_with(5)
    assert name_remove.await_count == 1


async def test_device_target_status_shared(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_lock: MockLock,
    entry: MockConfigEntry,
) -> None:
    """Test both lock entities report the same single status read."""
    mock_lock.push_lock.get_keycode.return_value = "4321"
    response = await _call_device(
        hass,
        device_registry,
        entry,
        "get_lock_credential_status",
        {"credential_index": 9},
        return_response=True,
    )

    mock_lock.push_lock.get_keycode.assert_awaited_once_with(9)
    expected = {
        "credential_exists": True,
        "name": None,
        "result": "pin",
        "pin": "4321",
    }
    assert response == {ENTITY_ID: expected, SECURE_ENTITY_ID: expected}


@pytest.mark.usefixtures("entry")
async def test_parallel_set_credential_different_slots_both_run(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """Test concurrent calls sharing a context but not data both run."""
    context = Context()
    await asyncio.gather(
        *(
            _call(
                hass,
                "set_lock_credential",
                {"credential_data": pin, "credential_index": slot},
                context=context,
            )
            for slot, pin in ((1, "1234"), (2, "5678"))
        )
    )

    assert sorted(c.args for c in mock_lock.push_lock.set_keycode.await_args_list) == [
        (1, "1234"),
        (2, "5678"),
    ]


@pytest.mark.usefixtures("entry")
async def test_parallel_status_different_slots_both_run(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """Test concurrent status reads for different slots return their own result."""
    mock_lock.push_lock.get_keycode.side_effect = {1: "1234"}.get
    context = Context()
    first, second = await asyncio.gather(
        *(
            _call(
                hass,
                "get_lock_credential_status",
                {"credential_index": slot},
                context=context,
                return_response=True,
            )
            for slot in (1, 2)
        )
    )

    assert first[ENTITY_ID] == {
        "credential_exists": True,
        "name": None,
        "result": "pin",
        "pin": "1234",
    }
    assert second[ENTITY_ID] == {
        "credential_exists": False,
        "name": None,
        "result": "empty",
        "pin": None,
    }


@pytest.mark.parametrize(
    ("service", "data", "method", "message"),
    [
        pytest.param(
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 5},
            "set_keycode",
            "Failed to communicate",
            id="set",
        ),
        pytest.param(
            "clear_lock_credential",
            {"credential_index": 5},
            "clear_keycode",
            "Failed to communicate",
            id="clear",
        ),
    ],
)
async def test_device_target_failure_runs_once(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    service: str,
    data: dict[str, Any],
    method: str,
    message: str,
) -> None:
    """Test a failure is raised once, translated, and not retried per entity."""
    getattr(mock_lock.push_lock, method).side_effect = YaleXSBLEError("boom")
    with pytest.raises(HomeAssistantError, match=message):
        await _call_device(hass, device_registry, entry, service, data)

    getattr(mock_lock.push_lock, method).assert_awaited_once()


async def test_device_target_invalid_pin(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_lock: MockLock,
    entry: MockConfigEntry,
) -> None:
    """Test PIN validation still raises when both entities are targeted."""
    with pytest.raises(ServiceValidationError, match="PIN"):
        await _call_device(
            hass,
            device_registry,
            entry,
            "set_lock_credential",
            {"credential_data": "12", "credential_index": 5},
        )
    mock_lock.push_lock.set_keycode.assert_not_awaited()


@pytest.mark.usefixtures("entry")
async def test_cancelled_set_credential_removes_record(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test cancelling a set after programming started drops the slot's record."""
    await _set_guest(hass)
    started = asyncio.Event()

    async def hang(slot: int, pin: str) -> None:
        started.set()
        await asyncio.Event().wait()

    mock_lock.push_lock.set_keycode.side_effect = hang
    task = hass.async_create_task(
        _call(
            hass,
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 3, "name": "New"},
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _stored_pins(hass_storage, entry) == {}


async def test_unload_waits_for_in_flight_name_save_before_removal(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test unload waits for an in-flight name save, so removal afterwards leaves no stored names."""
    original_write = Store._async_write_data
    write_started = asyncio.Event()
    write_done = asyncio.Event()
    release = asyncio.Event()

    async def blocked_write(self: Store, data: dict) -> None:
        async def write() -> None:
            write_started.set()
            await release.wait()
            await original_write(self, data)
            write_done.set()

        # An executor write keeps running when its awaiting task is cancelled.
        await asyncio.shield(hass.async_create_background_task(write(), "write"))

    with patch.object(Store, "_async_write_data", blocked_write):
        task = hass.async_create_task(
            _call(
                hass,
                "set_lock_credential",
                {"credential_data": "1234", "credential_index": 3, "name": "New"},
            )
        )
        await write_started.wait()
        hass.loop.call_later(0.05, release.set)
        await hass.config_entries.async_unload(entry.entry_id)
        assert write_done.is_set()
        await task
        await hass.config_entries.async_remove(entry.entry_id)
        await write_done.wait()

    assert STORAGE_KEY.format(entry.entry_id) not in hass_storage


@pytest.mark.usefixtures("entry")
async def test_cancelled_clear_credential_removes_record(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test cancelling a clear after it started drops the slot's record."""
    await _set_guest(hass)
    started = asyncio.Event()

    async def hang(slot: int) -> None:
        started.set()
        await asyncio.Event().wait()

    mock_lock.push_lock.clear_keycode.side_effect = hang
    task = hass.async_create_task(
        _call(hass, "clear_lock_credential", {"credential_index": 3})
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _stored_pins(hass_storage, entry) == {}


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            KeycodeError("clear_keycode", OperationError.KEYCODE_NOSPACE),
            GUEST,
            id="clear_failed",
        ),
        pytest.param(RuntimeError("not running"), GUEST, id="not_running"),
        pytest.param(BleakError("gone"), {}, id="bleak"),
    ],
)
async def test_failed_clear_credential_record_handling(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    error: Exception,
    expected: dict[str, dict[str, str | None]],
) -> None:
    """Test a failed clear keeps the slot's record only when the slot is unchanged."""
    await _set_guest(hass)
    mock_lock.push_lock.clear_keycode.side_effect = error
    with pytest.raises(HomeAssistantError):
        await _call(hass, "clear_lock_credential", {"credential_index": 3})
    assert _stored_pins(hass_storage, entry) == expected


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options", [pytest.param({"cloud_pin_rules": False}, id="stored_off")]
)
@pytest.mark.parametrize(
    ("capabilities", "refused_pin", "key", "placeholders", "sent_pin"),
    [
        pytest.param(
            FRONT_DOOR_CAPABILITIES,
            "12345",
            "invalid_pin_length",
            {"length": "6"},
            "123456",
            id="pin_length",
        ),
        pytest.param(
            {"lock": {"pinLengthMin": 4, "pinLengthMax": 8}},
            "123",
            "invalid_pin",
            {"min": "4", "max": "8"},
            "1234",
            id="pin_length_range",
        ),
        pytest.param(
            {"lock": {}},
            "123456",
            "invalid_pin_length",
            {"length": "5"},
            "12345",
            id="no_length_key",
        ),
    ],
)
async def test_pin_length_from_the_record(
    hass: HomeAssistant,
    mock_lock: MockLock,
    capabilities: dict[str, Any],
    refused_pin: str,
    key: str,
    placeholders: dict[str, str],
    sent_pin: str,
) -> None:
    """A PIN of a length the record does not allow is refused before any frame, and one of an allowed length is sent, on an entry that stored cloud_pin_rules off."""
    await async_setup_cloud(hass, [FRONT_DOOR_RECORD], {"front": capabilities})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": refused_pin, "credential_index": 12},
        )
    assert exc_info.value.translation_key == key
    assert exc_info.value.translation_placeholders == placeholders
    mock_lock.push_lock.set_keycode.assert_not_awaited()

    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": sent_pin, "credential_index": 12},
    )
    mock_lock.push_lock.set_keycode.assert_awaited_once_with(12, sent_pin)


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options", [pytest.param({"slot_range_source": "constants"}, id="stored_constants")]
)
async def test_slot_range_from_the_record(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """The record's top slot is sent and the slot past it is refused with the record's range, whatever slot_range_source value the entry stored."""
    await async_setup_cloud(
        hass, [FRONT_DOOR_RECORD], {"front": FRONT_DOOR_CAPABILITIES}
    )

    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "123456", "credential_index": 100},
    )
    mock_lock.push_lock.set_keycode.assert_awaited_once_with(100, "123456")

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": "567890", "credential_index": 101},
        )
    assert exc_info.value.translation_key == "invalid_slot"
    assert exc_info.value.translation_placeholders == {"min": "1", "max": "100"}
    mock_lock.push_lock.set_keycode.assert_awaited_once()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options", [pytest.param({"slot_field_width": True}, id="stored_field_width")]
)
@pytest.mark.parametrize(
    ("service", "data", "extra", "method"),
    [
        pytest.param(
            "set_lock_credential",
            {"credential_data": "123456", "credential_index": 0},
            {},
            "set_keycode",
            id="set_slot_0",
        ),
        pytest.param(
            "get_lock_credential_status",
            {"credential_index": 101},
            {"return_response": True},
            "get_keycode",
            id="status_past_the_top",
        ),
        pytest.param(
            "clear_lock_credential",
            {"credential_index": 101},
            {},
            "clear_keycode",
            id="clear_past_the_top",
        ),
        pytest.param(
            "get_lock_credential_status",
            {"credential_index": 65518},
            {"return_response": True},
            "get_keycode",
            id="status_master_code_slot",
        ),
        pytest.param(
            "set_lock_credential",
            {"credential_data": "123456", "credential_index": 65518},
            {},
            "set_keycode",
            id="set_master_code_slot",
        ),
    ],
)
async def test_every_action_refuses_a_slot_outside_the_record_range(
    hass: HomeAssistant,
    mock_lock: MockLock,
    service: str,
    data: dict[str, Any],
    extra: dict[str, Any],
    method: str,
) -> None:
    """A slot outside the record's range, the master code's slot included, is refused with the range before any frame, whatever slot_field_width value the entry stored."""
    await async_setup_cloud(
        hass, [FRONT_DOOR_RECORD], {"front": FRONT_DOOR_CAPABILITIES}
    )

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call(hass, service, data, **extra)
    assert exc_info.value.translation_key == "invalid_slot"
    assert exc_info.value.translation_placeholders == {"min": "1", "max": "100"}
    getattr(mock_lock.push_lock, method).assert_not_awaited()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("service", "data", "method"),
    [
        pytest.param(
            "set_lock_credential",
            {"credential_data": "123456", "credential_index": 100},
            "set_keycode",
            id="set",
        ),
        pytest.param(
            "clear_lock_credential",
            {"credential_index": 100},
            "clear_keycode",
            id="clear",
        ),
    ],
)
async def test_set_and_clear_refuse_the_master_code_slot_inside_the_range(
    hass: HomeAssistant,
    mock_lock: MockLock,
    service: str,
    data: dict[str, Any],
    method: str,
) -> None:
    """A set or clear at a masterPinSlot inside the record's range is refused with master_code_slot before any frame."""
    # No record on file puts masterPinSlot inside its slot range, so this record is constructed with the master code's slot at its top slot.
    await async_setup_cloud(
        hass,
        [FRONT_DOOR_RECORD],
        {"front": {"lock": {**FRONT_DOOR_CAPABILITIES["lock"], "masterPinSlot": 100}}},
    )

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call(hass, service, data)
    assert exc_info.value.translation_key == "master_code_slot"
    assert exc_info.value.translation_placeholders == {"slot": "100"}
    getattr(mock_lock.push_lock, method).assert_not_awaited()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        pytest.param(
            ["4321"],
            {
                "credential_exists": True,
                "name": "Guest",
                "result": "pin",
                "pin": "4321",
            },
            id="pin",
        ),
        pytest.param(
            [None],
            {
                "credential_exists": False,
                "name": None,
                "result": "empty",
                "pin": None,
            },
            id="empty",
        ),
        pytest.param(
            KeycodeError("get_keycode", OperationError.KEYCODE_NOSPACE),
            {
                "credential_exists": None,
                "name": None,
                "result": "KEYCODE_NOSPACE",
                "pin": None,
            },
            id="refusal",
        ),
        pytest.param(
            ValueError("Malformed PIN field"),
            {
                "credential_exists": None,
                "name": None,
                "result": "malformed",
                "pin": None,
            },
            id="malformed",
        ),
        pytest.param(
            TimeoutError("The lock did not answer get_keycode"),
            {
                "credential_exists": None,
                "name": None,
                "result": "timeout",
                "pin": None,
            },
            id="timeout",
        ),
    ],
)
async def test_status_result_returns_the_slots_result_and_pin_without_raising(
    hass: HomeAssistant,
    mock_lock: MockLock,
    side_effect: Any,
    expected: dict[str, bool | str | None],
) -> None:
    """With the status answer at its default, the status action returns the slot's result and the PIN the lock returned, and raises no error for a refusal, a malformed PIN field, or no answer."""
    await _set_guest(hass)
    mock_lock.push_lock.get_keycode.reset_mock()
    mock_lock.push_lock.get_keycode.side_effect = side_effect

    response = await _call(
        hass,
        "get_lock_credential_status",
        {"credential_index": 3},
        return_response=True,
    )

    mock_lock.push_lock.get_keycode.assert_awaited_once_with(3)
    assert response == {ENTITY_ID: expected}


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options",
    [
        pytest.param(
            {"occupancy_cloud_pins": False, "occupancy_read": False}, id="stored_off"
        )
    ],
)
async def test_set_refuses_a_slot_in_the_pins_block(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """A set at a slot that a created entry of the pins block holds is refused before any frame, on an entry that stored occupancy_cloud_pins and occupancy_read off."""
    # A constructed pins block with one entry in the created state, the one state whose PIN is not yet on the lock.
    record = {
        **FRONT_DOOR_RECORD,
        "pins": {
            "created": [
                {"slot": 100, "pin": "975310", "state": "created", "type": "pin"}
            ]
        },
    }
    await async_setup_cloud(hass, [record], {"front": FRONT_DOOR_CAPABILITIES})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": "123456", "credential_index": 100},
        )
    assert exc_info.value.translation_key == "slot_in_use"
    assert exc_info.value.translation_placeholders == {"slot": "100"}
    mock_lock.push_lock.get_keycode.assert_not_awaited()
    mock_lock.push_lock.set_keycode.assert_not_awaited()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options",
    [
        pytest.param(
            {"occupancy_cloud_pins": False, "occupancy_read": False}, id="stored_off"
        )
    ],
)
async def test_set_refuses_a_slot_that_holds_a_pin(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """A set at a slot the store does not hold is refused when the lock answers with a PIN, after one read and no write, on an entry that stored occupancy_cloud_pins and occupancy_read off."""
    mock_lock.push_lock.get_keycode.return_value = "975310"

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": "1234", "credential_index": 12},
        )
    assert exc_info.value.translation_key == "slot_not_empty"
    assert exc_info.value.translation_placeholders == {"slot": "12"}
    mock_lock.push_lock.get_keycode.assert_awaited_once_with(12)
    mock_lock.push_lock.set_keycode.assert_not_awaited()


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "options",
    [
        pytest.param(
            {"occupancy_cloud_pins": False, "occupancy_read": False}, id="stored_off"
        )
    ],
)
async def test_set_reads_the_slot_before_each_write(
    hass: HomeAssistant, mock_lock: MockLock
) -> None:
    """A set at an empty slot is read then written, and a second set at that slot, now in the store, is written after a read that answers the kept PIN, on an entry that stored occupancy_cloud_pins and occupancy_read off."""
    await _set_guest(hass)
    mock_lock.push_lock.get_keycode.assert_awaited_once_with(3)
    mock_lock.push_lock.set_keycode.assert_awaited_once_with(3, "4321")
    mock_lock.push_lock.get_keycode.reset_mock()
    mock_lock.push_lock.set_keycode.reset_mock()
    mock_lock.push_lock.get_keycode.return_value = "4321"

    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "8765", "credential_index": 3},
    )
    mock_lock.push_lock.get_keycode.assert_awaited_once_with(3)
    mock_lock.push_lock.set_keycode.assert_awaited_once_with(3, "8765")


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(None, id="empty"),
        pytest.param("4321", id="kept_pin"),
        pytest.param("8765", id="pin_being_set"),
    ],
)
async def test_set_at_a_kept_slot_writes_when_the_read_answers_empty_or_either_pin(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    answer: str | None,
) -> None:
    """A set at a slot the store holds is written after one read that answers an empty slot, the kept PIN, or the PIN being set."""
    await _set_guest(hass)
    mock_lock.push_lock.get_keycode.reset_mock()
    mock_lock.push_lock.set_keycode.reset_mock()
    mock_lock.push_lock.get_keycode.return_value = answer

    await _call(
        hass,
        "set_lock_credential",
        {"credential_data": "8765", "credential_index": 3},
    )

    mock_lock.push_lock.get_keycode.assert_awaited_once_with(3)
    mock_lock.push_lock.set_keycode.assert_awaited_once_with(3, "8765")
    assert _stored_pins(hass_storage, entry) == {"3": {"pin": "8765", "name": None}}


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    ("read", "exception", "translation_key", "placeholders", "expected"),
    [
        pytest.param(
            ["975310"],
            ServiceValidationError,
            "slot_holds_other_pin",
            {"slot": "3"},
            {},
            id="other_pin",
        ),
        pytest.param(
            KeycodeError("get_keycode", OperationError.NACK),
            HomeAssistantError,
            "keycode_error",
            {"error": str(KeycodeError("get_keycode", OperationError.NACK))},
            GUEST,
            id="read_refused",
        ),
    ],
)
async def test_set_at_a_kept_slot_is_refused_after_the_read(
    hass: HomeAssistant,
    mock_lock: MockLock,
    entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    read: list[str] | Exception,
    exception: type[HomeAssistantError],
    translation_key: str,
    placeholders: dict[str, str],
    expected: dict[str, dict[str, str | None]],
) -> None:
    """A set at a slot the store holds writes nothing when the read answers another PIN, which drops the record, or is refused, which keeps it."""
    await _set_guest(hass)
    mock_lock.push_lock.get_keycode.reset_mock()
    mock_lock.push_lock.set_keycode.reset_mock()
    mock_lock.push_lock.get_keycode.side_effect = read

    with pytest.raises(exception) as exc_info:
        await _call(
            hass,
            "set_lock_credential",
            {"credential_data": "8765", "credential_index": 3},
        )

    assert type(exc_info.value) is exception
    assert exc_info.value.translation_key == translation_key
    assert exc_info.value.translation_placeholders == placeholders
    mock_lock.push_lock.get_keycode.assert_awaited_once_with(3)
    mock_lock.push_lock.set_keycode.assert_not_awaited()
    assert _stored_pins(hass_storage, entry) == expected
