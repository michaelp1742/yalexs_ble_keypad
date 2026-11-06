"""Tests for the Yale Access Bluetooth Keypad integration."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)
from yalexs.lock import Lock, LockDetail

from custom_components.yalexs_ble_keypad.const import CLOUD_DOMAIN, OWNER_DOMAIN
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

ADDRESS = "AA:BB:CC:DD:EE:FF"
TITLE = "Front Door"
BACK_ADDRESS = "11:22:33:44:55:66"
BACK_TITLE = "Back Door"


async def async_advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Move the clock on and run the timers that fall due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed_exact(hass)
    await hass.async_block_till_done()


async def async_setup_owner(
    hass: HomeAssistant, address: str = ADDRESS, title: str = TITLE
) -> MockConfigEntry:
    """Add and load an entry of core's yalexs_ble for one lock."""
    owner = MockConfigEntry(
        domain=OWNER_DOMAIN,
        title=title,
        data={CONF_ADDRESS: address},
        unique_id=address,
    )
    owner.add_to_hass(hass)
    assert await hass.config_entries.async_setup(owner.entry_id)
    return owner


class YaleData:
    """Stand in for the yale entry's runtime data: a LockDetail per record, and a yalexs Lock for each on every read of locks."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        """Hold a LockDetail for each record, by device id."""
        self._details = {
            detail.device_id: detail
            for detail in (LockDetail(record) for record in records)
        }

    @property
    def locks(self) -> list[Lock]:
        """Return the locks."""
        return [
            Lock(
                device_id,
                {
                    "LockName": detail.device_name,
                    "HouseID": detail.house_id,
                    "UserType": "superuser",
                },
            )
            for device_id, detail in self._details.items()
        ]

    def get_device_detail(self, device_id: str) -> LockDetail:
        """Return the cloud record of a lock."""
        return self._details[device_id]


def cloud_record(lock_id: str, address: str, **fields: Any) -> dict[str, Any]:
    """Return a constructed cloud record of a lock: the keys LockDetail requires, the address, and the fields given."""
    return {
        "LockID": lock_id,
        "LockName": lock_id,
        "HouseID": "house",
        "SerialNumber": f"{lock_id}-serial",
        "currentFirmwareVersion": "1.0.0",
        "battery": 0.9,
        "Type": 1,
        "macAddress": address,
        **fields,
    }


async def async_setup_cloud(
    hass: HomeAssistant, records: list[dict[str, Any]]
) -> MockConfigEntry:
    """Add and load a yale entry that holds the cloud records."""
    entry = MockConfigEntry(domain=CLOUD_DOMAIN, data={"records": records})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    return entry
