"""Config flow for the Yale Access Bluetooth Keypad integration."""

from typing import Any, override

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import async_loaded_owners
from .const import (
    CONF_CLOUD_PIN_RULES,
    CONF_SLOT_FIELD_WIDTH,
    CONF_SLOT_RANGE_SOURCE,
    DEFAULT_OPTIONS,
    DOMAIN,
    SLOT_RANGE_CLOUD,
    SLOT_RANGE_CONSTANTS,
)
from .models import entry_options


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
                title=self._titles[address],
                data={CONF_ADDRESS: address},
                options=DEFAULT_OPTIONS,
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

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlowWithReload):
    """Handle the Yale Access Bluetooth Keypad options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the entry's options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = entry_options(self.config_entry)
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_CLOUD_PIN_RULES, default=options[CONF_CLOUD_PIN_RULES]
                    ): bool,
                    probatio.Required(
                        CONF_SLOT_RANGE_SOURCE, default=options[CONF_SLOT_RANGE_SOURCE]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SLOT_RANGE_CONSTANTS, SLOT_RANGE_CLOUD],
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key=CONF_SLOT_RANGE_SOURCE,
                        )
                    ),
                    probatio.Required(
                        CONF_SLOT_FIELD_WIDTH, default=options[CONF_SLOT_FIELD_WIDTH]
                    ): bool,
                }
            ),
        )
