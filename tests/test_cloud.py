"""Test reading the lock's PIN parameters from a loaded yale entry."""

from dataclasses import replace
from typing import Any

import pytest

from custom_components.yalexs_ble_keypad.cloud import (
    CloudPin,
    LockPinParameters,
    lock_pin_parameters,
)
from homeassistant.core import HomeAssistant

from . import ADDRESS, BACK_ADDRESS, async_setup_cloud, cloud_record

# A constructed pins block: the seven state lists of the lock's cloud record, each entry cut to slot, pin, state, and type.
FRONT_DOOR_PINS = {
    "created": [],
    "loaded": [{"slot": 1, "pin": "135790", "state": "loaded", "type": "pin"}],
    "updating": [],
    "enabling": [],
    "disabling": [],
    "disabled": [],
    "deleting": [{"slot": 2, "pin": "246802", "state": "deleting", "type": "pin"}],
}


def _parameters(
    *, record_read: bool, cloud_pins: tuple[CloudPin, ...] = ()
) -> LockPinParameters:
    """Return the PIN parameters of a lock whose record is not loaded or has no capabilities, with record_read as given."""
    return LockPinParameters(
        record_read=record_read,
        has_keypad=None,
        pin_length_min=4,
        pin_length_max=8,
        pin_slot_min=1,
        pin_slot_max=250,
        master_pin_slot=0xFFEE,
        cloud_pins=cloud_pins,
    )


@pytest.mark.parametrize(
    ("cloud_entries", "capabilities", "expected"),
    [
        pytest.param(
            [],
            {},
            _parameters(record_read=False),
            id="no_yale_entry",
        ),
        pytest.param(
            [[cloud_record("back", BACK_ADDRESS)]],
            {},
            _parameters(record_read=False),
            id="other_lock",
        ),
        pytest.param(
            [
                [
                    cloud_record("back", BACK_ADDRESS),
                    cloud_record("front", ADDRESS.lower(), pins=FRONT_DOOR_PINS),
                ]
            ],
            {},
            _parameters(
                record_read=True,
                cloud_pins=(
                    CloudPin(slot=1, pin="135790", state="loaded"),
                    CloudPin(slot=2, pin="246802", state="deleting"),
                ),
            ),
            id="lock_with_pins",
        ),
        pytest.param(
            [[cloud_record("front", ADDRESS)]],
            {},
            _parameters(record_read=True),
            id="lock_without_pins",
        ),
        pytest.param(
            [[cloud_record("front", ADDRESS)]],
            {"front": {"lock": {"integratedKeypad": False}}},
            replace(
                _parameters(record_read=True),
                has_keypad=False,
                pin_length_min=5,
                pin_length_max=5,
                master_pin_slot=None,
            ),
            id="lock_without_keypad_or_length",
        ),
    ],
)
async def test_lock_pin_parameters_from_yale_entry(
    hass: HomeAssistant,
    cloud_entries: list[list[dict[str, Any]]],
    capabilities: dict[str, dict[str, Any]],
    expected: LockPinParameters,
) -> None:
    """Test the PIN parameters from the loaded yale entries, with the pins block flattened across its states."""
    for records in cloud_entries:
        await async_setup_cloud(hass, records, capabilities)

    assert lock_pin_parameters(hass, ADDRESS) == expected
