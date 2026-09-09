# mzbotz/mz-file-store/features/shortener.py 

import aiohttp
import asyncio
import logging
from database.db import get_user

logger = logging.getLogger(__name__)


async def validate_shortener(domain: str, api_key: str) -> bool:
    """
    Tests if the given shortener domain and API key are valid by attempting
    to shorten a sample link.
    """
    try:
        url = f'https://{domain.strip()}/api'
        params = {'api': api_key.strip(), 'url': 'https://telegram.org'}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, ssl=False, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Validation failed: HTTP Status {response.status}")
                    return False
                
                data = await response.json(content_type=None)
                if data.get("status") == "success" and data.get("shortenedUrl"):
                    shortened_url = data["shortenedUrl"]
                    if isinstance(shortened_url, str) and shortened_url.startswith(('http://', 'https://')):
                        logger.info("Shortener validation successful.")
                        return True
        
        logger.error(f"Validation failed: API returned error: {data.get('message', 'Unknown error')}")
        return False
    except Exception as e:
        logger.error(f"Exception during shortener validation: {e}")
        return False


async def get_shortlink(link_to_shorten: str, user_id: int, step: int = 1) -> str:
    """
    Shortens the provided link based on the user's active shortener step (1, 2, or 3).
    Fallback to original link if step configuration is missing or attempts fail.
    """
    user = await get_user(user_id)
    if not user or not user.get('shortener_enabled'):
        return link_to_shorten

    # Dynamic step selection (shortener_url_1, shortener_url_2, shortener_url_3)
    # Agar specific step na mile to default base field fallback karega
    url_key = f'shortener_url_{step}'
    api_key = f'shortener_api_{step}'

    shortener_url = user.get(url_key) or user.get('shortener_url')
    shortener_api = user.get(api_key) or user.get('shortener_api')

    if not shortener_url or not shortener_api:
        logger.warning(f"Step {step} shortener not configured for user {user_id}. Returning original link.")
        return link_to_shorten

    domain = shortener_url.strip()
    api = shortener_api.strip()

    for attempt in range(3):
        try:
            req_url = f'https://{domain}/api'
            params = {'api': api, 'url': link_to_shorten}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(req_url, params=params, raise_for_status=True, ssl=False, timeout=10) as response:
                    data = await response.json(content_type=None)
                    
                    if data.get("status") == "success" and data.get("shortenedUrl"):
                        shortened_url = data["shortenedUrl"]
                        if isinstance(shortened_url, str) and shortened_url.startswith(('http://', 'https://')):
                            return shortened_url
                        else:
                            logger.error(f"Shortener API returned invalid format: {shortened_url}")
                    else:
                        logger.error(f"Shortener API error (Attempt {attempt + 1}/3): {data.get('message', 'Unknown error')}")

        except Exception as e:
            logger.error(f"HTTP Error during shortening step {step} (Attempt {attempt + 1}/3): {e}")
        
        if attempt < 2:
            await asyncio.sleep(1)

    logger.error(f"All shortener attempts failed for user {user_id} on Step {step}. Returning original link.")
    return link_to_shorten
                                                                   
