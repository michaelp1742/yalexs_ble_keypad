"""The Yale Access Bluetooth Keypad integration."""

from typing import TYPE_CHECKING

from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, OWNER_DOMAIN
from .models import YaleXSBLEKeypadConfigEntry, YaleXSBLEKeypadData

if TYPE_CHECKING:
    from homeassistant.components.yalexs_ble import YALEXSBLEConfigEntry


@callback
def async_loaded_owners(hass: HomeAssistant) -> dict[str, YALEXSBLEConfigEntry]:
    """Return the loaded entries of core's yalexs_ble by lock address."""
    return {
        owner.data[CONF_ADDRESS]: owner
        for owner in hass.config_entries.async_loaded_entries(OWNER_DOMAIN)
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: YaleXSBLEKeypadConfigEntry
) -> bool:
    """Set up the entry on the PushLock of core's loaded entry for the lock."""
    address = entry.data[CONF_ADDRESS]
    if (owner := async_loaded_owners(hass).get(address)) is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="owner_not_loaded"
        )
    entry.runtime_data = YaleXSBLEKeypadData(
        title=owner.title, address=address, lock=owner.runtime_data.lock
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
