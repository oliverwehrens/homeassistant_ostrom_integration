"""Config flow for Ostrom integration."""
from homeassistant import config_entries
import voluptuous as vol
import logging
import requests
from . import DOMAIN
from .auth import get_access_token

ENV_SANDBOX = "sandbox"
ENV_PRODUCTION = "production"

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required("client_id"): str,
    vol.Required("client_secret"): str,
    vol.Required("zip_code"): str,
    vol.Required("environment", default=ENV_PRODUCTION): vol.In({
        ENV_SANDBOX: "Sandbox",
        ENV_PRODUCTION: "Production"
    }),
})

@config_entries.HANDLERS.register(DOMAIN)
class OstromConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ostrom integration."""
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                _LOGGER.debug("Validating Ostrom credentials: %s", user_input["client_id"])
                valid = await self.hass.async_add_executor_job(
                    self.validate_credentials,
                    user_input["client_id"],
                    user_input["client_secret"],
                    user_input["zip_code"],
                    user_input["environment"]
                )
                
                if valid:
                    _LOGGER.info("Successfully configured Ostrom integration")
                    return self.async_create_entry(
                        title=f"Ostrom Energy ({user_input['zip_code']})",
                        data=user_input
                    )
                else:
                    _LOGGER.warning("Failed to validate Ostrom credentials")
                    errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.error("Error during Ostrom validation: %s", str(e), exc_info=True)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OstromOptionsFlowHandler(config_entry)

    def validate_credentials(self, client_id: str, client_secret: str, zip_code: str, environment: str) -> bool:
        """Validate the credentials."""
        try:
            env_prefix = f"{environment}.ostrom-api.io"
            auth_url = f"https://auth.{env_prefix}/oauth2/token"
            
            auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
            payload = {"grant_type": "client_credentials"}
            
            response = requests.post(auth_url, auth=auth, data=payload)
            response.raise_for_status()
            data = response.json()
            access_token = data.get("access_token")
            
            if not access_token:
                _LOGGER.error("Access token not found in the response.")
                return False
            
            # Validate token with /me endpoint
            me_url = f"https://{env_prefix}/me"
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

class OstromOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Ostrom options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            # Update the config entry with new values
            return self.async_create_entry(title="", data=user_input)

        # Use current values as defaults
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("client_id", default=self.config_entry.data.get("client_id")): str,
                vol.Required("client_secret", default=self.config_entry.data.get("client_secret")): str,
                vol.Required("zip_code", default=self.config_entry.data.get("zip_code")): str,
                vol.Required("environment", default=self.config_entry.data.get("environment", ENV_PRODUCTION)): vol.In({
                    ENV_SANDBOX: "Sandbox",
                    ENV_PRODUCTION: "Production"
                }),
            }),
            errors=errors
        ) 