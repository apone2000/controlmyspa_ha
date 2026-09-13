"""Config flow for the ControlMySpa integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    ControlMySpaAuthError,
    ControlMySpaClient,
    ControlMySpaConnectionError,
    ControlMySpaError,
    ControlMySpaNoSpaError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import ControlMySpaConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        )
    }
)


class ControlMySpaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup and any later re-authentication."""

    VERSION = 1

    async def _async_validate(self, email: str, password: str) -> dict[str, Any]:
        """Log in and fetch the spa, returning its identifying fields."""
        client = ControlMySpaClient(
            session=async_get_clientsession(self.hass),
            email=email,
            password=password,
        )
        await client.async_login()
        spa = await client.async_get_spa()
        return {"id": str(spa.get("_id") or ""), "serial": spa.get("serialNumber")}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials and confirm they work before creating the entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            try:
                spa = await self._async_validate(email, user_input[CONF_PASSWORD])
            except ControlMySpaAuthError:
                errors["base"] = "invalid_auth"
            except ControlMySpaConnectionError:
                errors["base"] = "cannot_connect"
            except ControlMySpaNoSpaError:
                errors["base"] = "no_spa"
            except ControlMySpaError:
                _LOGGER.exception("Unexpected error validating ControlMySpa account")
                errors["base"] = "unknown"
            else:
                # Prefer the serial number: it survives the account being
                # re-registered, whereas the record id may not.
                await self.async_set_unique_id(spa["serial"] or spa["id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=email, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the stored credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a fresh password for the existing account."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await self._async_validate(
                    entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except ControlMySpaAuthError:
                errors["base"] = "invalid_auth"
            except ControlMySpaConnectionError:
                errors["base"] = "cannot_connect"
            except ControlMySpaError:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ControlMySpaConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return ControlMySpaOptionsFlow()


class ControlMySpaOptionsFlow(OptionsFlow):
    """Allow the poll interval to be tuned after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Present and store the poll interval."""
        if user_input is not None:
            # The selector yields a float; the coordinator wants whole seconds.
            interval = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(data={CONF_SCAN_INTERVAL: interval})

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=5,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
