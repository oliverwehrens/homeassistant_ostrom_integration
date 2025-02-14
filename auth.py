import aiohttp
import logging

_LOGGER = logging.getLogger(__name__)

AUTH_URL_TEMPLATE = "https://auth.{env_prefix}/oauth2/token"

async def get_access_token(client_id, client_secret, environment):
    env_prefix = "sandbox.ostrom-api.io" if environment == "sandbox" else "production.ostrom-api.io"
    auth_url = AUTH_URL_TEMPLATE.format(env_prefix=env_prefix)
    auth = aiohttp.BasicAuth(client_id, client_secret)
    payload = {"grant_type": "client_credentials"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(auth_url, auth=auth, data=payload) as response:
                response.raise_for_status()
                data = await response.json()
                access_token = data.get("access_token")
                expires_in = data.get("expires_in", 3600)  # Default to 3600 seconds if not provided
                if not access_token:
                    _LOGGER.error("Access token not found in the response: %s", data)
                    raise ValueError("Access token not found in the response")
                _LOGGER.debug("Received access token: %s", access_token)
                return {"access_token": access_token, "expires_in": expires_in}
    except aiohttp.ClientError as e:
        _LOGGER.error("Error fetching access token: %s", str(e))
        raise 