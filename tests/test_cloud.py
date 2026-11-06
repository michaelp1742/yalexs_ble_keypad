"""Test reading the lock's PIN parameters from a loaded yale entry."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.yalexs_ble_keypad.cloud import (
    CloudPin,
    LockPinParameters,
    lock_pin_parameters,
)
from custom_components.yalexs_ble_keypad.const import CLOUD_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.core import HomeAssistant

from . import ADDRESS, BACK_ADDRESS

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


class _YaleData:
    """Stand in for the yale entry's runtime data with the locks' cloud records."""

    def __init__(self, records: dict[str, dict[str, Any]]) -> None:
        """Hold the records by device id."""
        self._details = {
            device_id: SimpleNamespace(mac_address=record["macAddress"], raw=record)
            for device_id, record in records.items()
        }

    @property
    def locks(self) -> list[SimpleNamespace]:
        """Return the locks."""
        return [SimpleNamespace(device_id=device_id) for device_id in self._details]

    def get_device_detail(self, device_id: str) -> SimpleNamespace:
        """Return the cloud record of a lock."""
        return self._details[device_id]


class _CloudConfigFlow(ConfigFlow):
    """Stand in for the config flow of core's yale."""


@pytest.fixture(autouse=True)
def mock_cloud_integration(hass: HomeAssistant) -> Iterator[None]:
    """Stand in for core's yale, which needs the cloud."""

    async def _async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        entry.runtime_data = _YaleData(entry.data["records"])
        return True

    mock_integration(
        hass, MockModule(CLOUD_DOMAIN, async_setup_entry=_async_setup_entry)
    )
    mock_platform(hass, f"{CLOUD_DOMAIN}.config_flow")
    with mock_config_flow(CLOUD_DOMAIN, _CloudConfigFlow):
        yield


@pytest.mark.parametrize(
    ("cloud_entries", "expected"),
    [
        pytest.param(
            [],
            LockPinParameters(record_read=False, cloud_pins=()),
            id="no_yale_entry",
        ),
        pytest.param(
            [{"back": {"macAddress": BACK_ADDRESS}}],
            LockPinParameters(record_read=False, cloud_pins=()),
            id="other_lock",
        ),
        pytest.param(
            [
                {
                    "back": {"macAddress": BACK_ADDRESS},
                    "front": {"macAddress": ADDRESS, "pins": FRONT_DOOR_PINS},
                }
            ],
            LockPinParameters(
                record_read=True,
                cloud_pins=(
                    CloudPin(slot=1, pin="135790", state="loaded"),
                    CloudPin(slot=2, pin="246802", state="deleting"),
                ),
            ),
            id="lock_with_pins",
        ),
        pytest.param(
            [{"front": {"macAddress": ADDRESS}}],
            LockPinParameters(record_read=True, cloud_pins=()),
            id="lock_without_pins",
        ),
    ],
)
async def test_lock_pin_parameters_from_yale_entry(
    hass: HomeAssistant,
    cloud_entries: list[dict[str, dict[str, Any]]],
    expected: LockPinParameters,
) -> None:
    """Test the PIN parameters from the loaded yale entries, with the pins block flattened across its states."""
    for records in cloud_entries:
        cloud_entry = MockConfigEntry(domain=CLOUD_DOMAIN, data={"records": records})
        cloud_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(cloud_entry.entry_id)

    assert lock_pin_parameters(hass, ADDRESS) == expected
