"""Fixtures for the Yale Access Bluetooth Keypad tests."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)
from yalexs_ble import PushLock

from custom_components.yalexs_ble_keypad.const import CLOUD_DOMAIN, DOMAIN, OWNER_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import ADDRESS, TITLE, YaleData, async_setup_owner


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in every test."""


async def _async_setup_owner_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load core's entry with a new PushLock, as core does on every load."""
    entry.runtime_data = Mock(
        lock=create_autospec(PushLock, instance=True, address=entry.data[CONF_ADDRESS])
    )
    return True


class _OwnerConfigFlow(ConfigFlow):
    """Stand in for the config flow of core's yalexs_ble."""


@pytest.fixture(autouse=True)
def mock_owner_integration(hass: HomeAssistant) -> Iterator[None]:
    """Stand in for core's yalexs_ble, which needs Bluetooth."""
    mock_integration(
        hass,
        MockModule(
            OWNER_DOMAIN,
            async_setup_entry=_async_setup_owner_entry,
            async_unload_entry=AsyncMock(return_value=True),
        ),
    )
    mock_platform(hass, f"{OWNER_DOMAIN}.config_flow")
    with mock_config_flow(OWNER_DOMAIN, _OwnerConfigFlow):
        yield


async def _async_setup_cloud_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load the yale entry with the cloud records its data holds."""
    entry.runtime_data = YaleData(entry.data["records"])
    return True


class _CloudConfigFlow(ConfigFlow):
    """Stand in for the config flow of core's yale."""


@pytest.fixture(autouse=True)
def mock_cloud_integration(hass: HomeAssistant) -> Iterator[None]:
    """Stand in for core's yale, which needs the cloud."""
    mock_integration(
        hass, MockModule(CLOUD_DOMAIN, async_setup_entry=_async_setup_cloud_entry)
    )
    mock_platform(hass, f"{CLOUD_DOMAIN}.config_flow")
    with mock_config_flow(CLOUD_DOMAIN, _CloudConfigFlow):
        yield


@pytest.fixture
async def owner_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a loaded entry of core's yalexs_ble."""
    return await async_setup_owner(hass)


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return the keypad entry for the lock, not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        data={CONF_ADDRESS: ADDRESS},
        unique_id=ADDRESS,
    )
    entry.add_to_hass(hass)
    return entry
