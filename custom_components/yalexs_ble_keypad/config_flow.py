"""Config flow for the Yale Access Bluetooth Keypad integration."""

from typing import Any, override

import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from . import async_loaded_owners
from .const import DOMAIN


class YaleXSBLEKeypadConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yale Access Bluetooth Keypad."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._titles: dict[str, str] = {}

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick a lock that core's yalexs_ble has loaded."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._titles[address], data={CONF_ADDRESS: address}
            )

        current_addresses = self._async_current_ids()
        self._titles = {
            address: owner.title
            for address, owner in async_loaded_owners(self.hass).items()
            if address not in current_addresses
        }
        if not self._titles:
            return self.async_abort(reason="no_locks")

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ADDRESS): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=address, label=title)
                                for address, title in self._titles.items()
                            ]
                        )
                    )
                }
            ),
        )
