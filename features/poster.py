# features/poster.py

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
    for i in range(len(words), max(0, min(1, len(words)) - 1), -1):
        if i > 0:
            queries.append(' '.join(words[:i]))
    return list(dict.fromkeys(queries))

async def _find_poster_from_imdb(query: str, target_year: str = None):
    """Get poster from IMDb, optionally enforcing exact year match."""
    try:
        clean_query = re.sub(r'\s+', '+', query.strip())
        search_url = f"https://www.imdb.com/find?q={clean_query}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept-Language': 'en-US,en;q=0.5'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(search_url, timeout=10) as resp:
                if resp.status != 200: return None
                soup = BeautifulSoup(await resp.text(), 'html.parser')
                
                # Agar year diya hai toh saare search items scan karke exact year wala item choose karein
                items = soup.select("li.ipc-metadata-list-summary-item")
                selected_link = None
                
                if target_year and items:
                    for item in items:
                        text_content = item.get_text()
                        if str(target_year) in text_content:
                            link = item.select_one("a.ipc-metadata-list-summary-item__t")
                            if link and link.get('href'):
                                selected_link = link['href']
                                break
                
                if not selected_link:
                    # Target year specify nahi hai toh first item lo, warna bina year match ke IMDb blind guess mat lo
                    if target_year:
                        return None
                    first_link = soup.select_one("a.ipc-metadata-list-summary-item__t")
                    if first_link and first_link.get('href'):
                        selected_link = first_link['href']

                if not selected_link: return None
                
                movie_url = "https://www.imdb.com" + selected_link.split('?')[0]
                async with session.get(movie_url, timeout=10) as movie_resp:
                    if movie_resp.status != 200: return None
                    movie_soup = BeautifulSoup(await movie_resp.text(), 'html.parser')
                    img_tag = movie_soup.select_one('div[data-testid="hero-media__poster"] img.ipc-image')
                    if img_tag and img_tag.get('src'):
                        return img_tag['src'].split('_V1_')[0] + "_V1_FMjpg_UX1000_.jpg"
    except Exception:
        return None
    return None

async def _find_poster_from_tmdb(query: str, target_year: str = None):
    """Get poster from TMDB with strict release year verification."""
    if not Config.TMDB_API_KEY: return None
    try:
        search_url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "api_key": Config.TMDB_API_KEY, 
            "query": query, 
            "include_adult": "false"
        }
        if target_year:
            params['primary_release_year'] = str(target_year)

        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, timeout=10) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                results = data.get('results', [])
                if not results: return None

                # 1. First priority: Exact Year Match
                if target_year:
                    for item in results:
                        rel_date = item.get('release_date') or item.get('first_air_date') or ""
                        if str(target_year) in rel_date and item.get("poster_path"):
                            return f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
                    return None # Year match nahi mila toh wrong year ka poster lene se bachein

                # 2. No year specified: Best match
                for item in results:
                    if item.get("poster_path"):
                        return f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
    except Exception:
        return None
    return None

async def get_poster(query: str, year: str = None):
    sanitized_query = query.replace('"', '').strip()
    search_queries = generate_search_queries(sanitized_query)
    logger.info(f"Waterfall Search: Starting for '{sanitized_query}' (Year: {year}). Queries: {search_queries}")

    # PHASE 1: Try ALL sources strictly WITH YEAR first (Wrong movie posters se bachne ke liye)
    if year:
        for sq in search_queries:
            # IMDb with exact year check
            poster = await _find_poster_from_imdb(f"{sq} {year}", target_year=year)
            if poster: 
                logger.info(f"SUCCESS: IMDb matched with year for '{sq}' ({year})")
                return poster
            
            # TMDB with exact year check
            poster = await _find_poster_from_tmdb(sq, target_year=year)
            if poster: 
                logger.info(f"SUCCESS: TMDB matched with year for '{sq}' ({year})")
                return poster

    # PHASE 2: Fallback without year (sirf tab chalega jab movie ka year match na mila ho ya provide na ho)
    for sq in search_queries:
        poster = await _find_poster_from_imdb(sq)
        if poster: 
            logger.info(f"SUCCESS: IMDb without year for '{sq}'")
            return poster

        poster = await _find_poster_from_tmdb(sq)
        if poster: 
            logger.info(f"SUCCESS: TMDB without year for '{sq}'")
            return poster

    logger.error(f"Waterfall Search: All attempts failed for base query '{query}'.")
    return None
