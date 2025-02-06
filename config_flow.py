from homeassistant import config_entries
from homeassistant.core import HomeAssistant
import voluptuous as vol
import requests
import logging
from . import DOMAIN  # Ensure DOMAIN is imported correctly
from requests.auth import HTTPBasicAuth
from .auth import get_access_token

ENV_SANDBOX = "sandbox"
ENV_PRODUCTION = "production"

_LOGGER = logging.getLogger(__name__)


class OstromConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            valid = await self.hass.async_add_executor_job(
                self.validate_credentials,
                user_input["client_id"],
                user_input["client_secret"],
                user_input["zip_code"],
                user_input["environment"]
            )
            
            if valid:
                return self.async_create_entry(
                    title="Ostrom Energy",
                    data=user_input
                )
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("client_id"): str,
                vol.Required("client_secret"): str,
                vol.Required("zip_code"): str,
                vol.Required("environment", default=ENV_SANDBOX): vol.In({
                    ENV_SANDBOX: "Sandbox",
                    ENV_PRODUCTION: "Production"
                }),
            }),
            errors=errors
        )

    def validate_credentials(self, client_id: str, client_secret: str, zip_code: str, environment: str) -> bool:
        try:
            env_prefix = "production" if environment == ENV_PRODUCTION else ENV_SANDBOX
            auth_url = f"https://auth.{env_prefix}.ostrom-api.io/oauth2/token"

            
            access_token = get_access_token(client_id, client_secret, auth_url)
            if not access_token:
                _LOGGER.error("Access token not found in the response.")
                return False
            
            # Validate token with /me endpoint
            me_url = f"https://{env_prefix}.ostrom-api.io/me"
            headers = {"Authorization": f"Bearer {access_token}"}
            response = requests.get(me_url, headers=headers)
            
            if response.status_code == 200:
                _LOGGER.debug("Credentials validated successfully with /me endpoint.")
                return True
            else:
                _LOGGER.error(
                    "Validation with /me endpoint failed. Status code: %s, Response: %s",
                    response.status_code,
                    response.text
                )
                return False
        
        except requests.exceptions.RequestException as e:
            _LOGGER.error(
                "Request exception during validation: %s. Details: %s",
                type(e).__name__,
                str(e)
            )
            return False 