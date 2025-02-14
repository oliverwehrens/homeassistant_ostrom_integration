import aiohttp
import logging
from typing import Dict, Any

_LOGGER = logging.getLogger(__name__)

AUTH_URL_TEMPLATE = "https://auth.{env_prefix}/oauth2/token"
ME_URL_TEMPLATE = "https://{env_prefix}/me"  # Note: this URL format needs to match the API

async def get_access_token(client_id: str, client_secret: str, environment: str) -> Dict[str, Any]:
    """Get access token from Ostrom API asynchronously."""
    env_prefix = "sandbox.ostrom-api.io" if environment == "sandbox" else "production.ostrom-api.io"
    auth_url = AUTH_URL_TEMPLATE.format(env_prefix=env_prefix)
    me_url = ME_URL_TEMPLATE.format(env_prefix=env_prefix)
    
    auth = aiohttp.BasicAuth(client_id, client_secret)
    payload = {"grant_type": "client_credentials"}

    async with aiohttp.ClientSession() as session:
        try:
            # Get token
            async with session.post(auth_url, auth=auth, data=payload) as response:
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
                
        except aiohttp.ClientError as e:
            _LOGGER.error("Error during API request: %s", str(e))
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