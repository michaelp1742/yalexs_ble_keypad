"""The Yale Access Bluetooth Keypad integration."""

from typing import TYPE_CHECKING

from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, OWNER_DOMAIN
from .models import YaleXSBLEKeypadConfigEntry, YaleXSBLEKeypadData
from .services import async_setup_services
from .store import PinStore, async_remove_pin_store

if TYPE_CHECKING:
    from homeassistant.components.yalexs_ble import YALEXSBLEConfigEntry

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@callback
def async_loaded_owners(hass: HomeAssistant) -> dict[str, YALEXSBLEConfigEntry]:
    """Return the loaded entries of core's yalexs_ble by lock address."""
    return {
        owner.data[CONF_ADDRESS]: owner
        for owner in hass.config_entries.async_loaded_entries(OWNER_DOMAIN)
    }


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the keypad PIN actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry
) -> bool:
    """Set up the entry on the PushLock of core's loaded entry for the lock."""
    address = entry.data[CONF_ADDRESS]
    if (owner := async_loaded_owners(hass).get(address)) is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="owner_not_loaded"
        )
    pins = PinStore(hass, entry)
    await pins.async_load()
    entry.runtime_data = YaleXSBLEKeypadData(
        title=owner.title,
        address=address,
        lock=owner.runtime_data.lock,
        pins=pins,
    )

    reload_scheduled = False

    @callback
    def _async_owner_changed() -> None:
        """Schedule one reload of this entry when core's entry changes state."""
        nonlocal reload_scheduled
        if reload_scheduled:
            return
        reload_scheduled = True
        # A reload started inside the listener loop of core's entry can remove this
        # listener while the loop runs, and the loop then skips the listener after it.
        hass.loop.call_soon(hass.config_entries.async_schedule_reload, entry.entry_id)

    entry.async_on_unload(owner.async_on_state_change(_async_owner_changed))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry
) -> bool:
    """Unload a config entry."""
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry
) -> None:
    """Remove stored data when the config entry is removed."""
    await async_remove_pin_store(hass, entry.entry_id)
