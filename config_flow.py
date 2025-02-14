from homeassistant import config_entries
import voluptuous as vol
import logging
from . import DOMAIN
from .auth import validate_auth

ENV_SANDBOX = "sandbox"
ENV_PRODUCTION = "production"

_LOGGER = logging.getLogger(__name__)

class OstromConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ostrom integration."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                valid = await self.hass.async_add_executor_job(
                    validate_auth,
                    user_input["client_id"],
                    user_input["client_secret"],
                    user_input["environment"]
                )
                
                if valid:
                    return self.async_create_entry(
                        title=f"Ostrom Energy ({user_input['zip_code']})",
                        data=user_input
                    )
                else:
                    errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.error("Error during validation: %s", str(e))
                errors["base"] = "cannot_connect"

        # Show initial form
        data_schema = vol.Schema({
            vol.Required("client_id"): str,
            vol.Required("client_secret"): str,
            vol.Required("zip_code"): str,
            vol.Required("environment", default=ENV_PRODUCTION): vol.In({
                ENV_SANDBOX: "Sandbox",
                ENV_PRODUCTION: "Production"
            }),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

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