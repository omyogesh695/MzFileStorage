import asyncio
import aiohttp
from bs4 import BeautifulSoup
import logging
import re
from config import Config

logger = logging.getLogger(__name__)

def generate_search_queries(title: str):
    """Generates a list of progressively shorter search queries from a title."""
    words = title.split()
    queries = []
    # Generate queries from the full title down to 2 words
    for i in range(len(words), max(0, min(1, len(words)) - 1), -1):
        if i > 0:
            queries.append(' '.join(words[:i]))
    return list(dict.fromkeys(queries)) # Return unique queries

async def _find_poster_from_imdb(query: str):
    """Internal function to get the best-guess poster from IMDb for a single query."""
    try:
        clean_query = re.sub(r'\s+', '+', query)
        search_url = f"https://www.imdb.com/find?q={clean_query}"
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en-US,en;q=0.5'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(search_url, timeout=10) as resp:
                if resp.status != 200: return None
                soup = BeautifulSoup(await resp.text(), 'html.parser')
                result_link = soup.select_one("a.ipc-metadata-list-summary-item__t")
                if not result_link or not result_link.get('href'): return None
                
                movie_url = "https://www.imdb.com" + result_link['href'].split('?')[0]
                async with session.get(movie_url, timeout=10) as movie_resp:
                    if movie_resp.status != 200: return None
                    movie_soup = BeautifulSoup(await movie_resp.text(), 'html.parser')
                    img_tag = movie_soup.select_one('div[data-testid="hero-media__poster"] img.ipc-image')
                    if img_tag and img_tag.get('src'):
                        poster_url = img_tag['src'].split('_V1_')[0] + "_V1_FMjpg_UX1000_.jpg"
                        return poster_url
    except Exception:
        return None
    return None

async def _find_poster_from_tmdb(query: str, year: str = None):
    """Internal function to get the best-guess poster from TMDB for a single query."""
    if not Config.TMDB_API_KEY: return None
    try:
        search_url = "https://api.themoviedb.org/3/search/multi"
        params = {"api_key": Config.TMDB_API_KEY, "query": query, "include_adult": "false"}
        if year: params['year'] = year
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, timeout=10) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                if data.get('results') and data['results'][0].get("poster_path"):
                    return f"https://image.tmdb.org/t/p/w500{data['results'][0]['poster_path']}"
    except Exception:
        return None
    return None

async def get_poster(query: str, year: str = None):
    """
    The definitive 'waterfall' poster finder. It tries every possible combination
    of truncated queries and sources until it gets a match.
    """
    # Final guardrail: Sanitize the query to remove stray characters like quotes
    sanitized_query = query.replace('"', '').strip()
    
    search_queries = generate_search_queries(sanitized_query)
    logger.info(f"Waterfall Search: Starting for '{sanitized_query}'. Queries: {search_queries}")

    for sq in search_queries:
        logger.info(f"Waterfall Search: Trying query '{sq}'...")
        
        # --- IMDb First (User Preference) ---
        if year:
            poster = await _find_poster_from_imdb(f"{sq} {year}")
            if poster: logger.info(f"SUCCESS: IMDb with year for '{sq}'"); return poster
        
        poster = await _find_poster_from_imdb(sq)
        if poster: logger.info(f"SUCCESS: IMDb without year for '{sq}'"); return poster
        
        # --- TMDB Second (API Fallback) ---
        if year:
            poster = await _find_poster_from_tmdb(sq, year)
            if poster: logger.info(f"SUCCESS: TMDB with year for '{sq}'"); return poster
        
        poster = await _find_poster_from_tmdb(sq)
        if poster: logger.info(f"SUCCESS: TMDB without year for '{sq}'"); return poster

    logger.error(f"Waterfall Search: All attempts failed for base query '{query}'.")
    return None
