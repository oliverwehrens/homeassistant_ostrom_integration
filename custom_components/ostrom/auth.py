import aiohttp
import asyncio
import logging
from typing import Dict, Any, Optional

_LOGGER = logging.getLogger(__name__)

AUTH_URL_TEMPLATE = "https://auth.{env_prefix}/oauth2/token"
ME_URL_TEMPLATE = "https://{env_prefix}/me"  # Note: this URL format needs to match the API

# Retry settings for transient rate limiting (HTTP 429) on the token endpoint.
# Waits roughly 5s, 15s, 45s between attempts (capped), honouring Retry-After
# when the server provides it. This lets a cold start survive a short 429 burst
# instead of immediately leaving all sensors unavailable.
_TOKEN_MAX_ATTEMPTS = 4
_TOKEN_BACKOFF_BASE = 5   # seconds
_TOKEN_BACKOFF_CAP = 120  # seconds


async def get_access_token(client_id: str, client_secret: str, environment: str) -> Optional[Dict[str, Any]]:
    """Get access token from Ostrom API asynchronously.

    Retries with exponential backoff on HTTP 429 (rate limit) and transient
    network errors. Returns None if no token could be obtained.
    """
    env_prefix = "sandbox.ostrom-api.io" if environment == "sandbox" else "production.ostrom-api.io"
    auth_url = AUTH_URL_TEMPLATE.format(env_prefix=env_prefix)
    me_url = ME_URL_TEMPLATE.format(env_prefix=env_prefix)

    auth = aiohttp.BasicAuth(client_id, client_secret)
    payload = {"grant_type": "client_credentials"}

    async with aiohttp.ClientSession() as session:
        for attempt in range(1, _TOKEN_MAX_ATTEMPTS + 1):
            try:
                # Get token
                async with session.post(auth_url, auth=auth, data=payload) as response:
                    # Handle rate limiting explicitly so we can back off and retry.
                    if response.status == 429:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after is not None and str(retry_after).isdigit():
                            delay = min(int(retry_after), _TOKEN_BACKOFF_CAP)
                        else:
                            delay = min(_TOKEN_BACKOFF_BASE * (3 ** (attempt - 1)), _TOKEN_BACKOFF_CAP)

                        if attempt < _TOKEN_MAX_ATTEMPTS:
                            _LOGGER.warning(
                                "Ostrom token endpoint rate limited (HTTP 429), "
                                "attempt %s/%s. Retrying in %s s.",
                                attempt, _TOKEN_MAX_ATTEMPTS, delay,
                            )
                            await asyncio.sleep(delay)
                            continue

                        _LOGGER.error(
                            "Ostrom token endpoint still rate limited (HTTP 429) "
                            "after %s attempts. Giving up for this cycle.",
                            _TOKEN_MAX_ATTEMPTS,
                        )
                        return None

                    response.raise_for_status()
                    data = await response.json()
                    access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)

                    if not access_token:
                        _LOGGER.error("Access token not found in the response: %s", data)
                        return None

                    # Validate token
                    headers = {"Authorization": f"Bearer {access_token}"}
                    async with session.get(me_url, headers=headers) as me_response:
                        if me_response.status != 200:
                            error_text = await me_response.text()
                            _LOGGER.error(
                                "Validation with /me endpoint failed. Status: %s, Response: %s",
                                me_response.status,
                                error_text
                            )
                            return None

                    _LOGGER.debug("Access token validated successfully")
                    return {"access_token": access_token, "expires_in": expires_in}

            except aiohttp.ClientResponseError as e:
                # Non-429 HTTP error (e.g. 401/403/500): retrying will not help.
                _LOGGER.error("HTTP error from Ostrom auth endpoint: %s", str(e))
                return None

            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                # Transient network/timeout error: back off and retry.
                _LOGGER.warning(
                    "Network/timeout error contacting Ostrom auth endpoint "
                    "(attempt %s/%s): %s",
                    attempt, _TOKEN_MAX_ATTEMPTS, str(e),
                )
                if attempt < _TOKEN_MAX_ATTEMPTS:
                    await asyncio.sleep(_TOKEN_BACKOFF_BASE)
                    continue
                return None

            except aiohttp.ClientError as e:
                _LOGGER.error("Error during API request: %s", str(e))
                return None

    return None


def validate_auth(client_id: str, client_secret: str, environment: str) -> bool:
    """Synchronous validation for config flow."""
    import asyncio
    import platform

    try:
        if platform.system() == "Windows":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(get_access_token(client_id, client_secret, environment))
            return result is not None and "access_token" in result
        finally:
            loop.close()

    except Exception as e:
        _LOGGER.error("Auth validation failed: %s", str(e))
        return False
