# features/poster.py

import asyncio
import aiohttp
from bs4 import BeautifulSoup
import logging
import re
from config import Config

logger = logging.getLogger(__name__)

# Safe fuzzy import
try:
    from rapidfuzz import fuzz
except ImportError:
    import difflib
    class FuzzFallback:
        @staticmethod
        def ratio(s1, s2):
            return int(difflib.SequenceMatcher(None, s1, s2).ratio() * 100)
        @staticmethod
        def token_sort_ratio(s1, s2):
            return int(difflib.SequenceMatcher(None, " ".join(sorted(s1.split())), " ".join(sorted(s2.split()))).ratio() * 100)
    fuzz = FuzzFallback()


def _is_title_match(query_norm: str, candidate_norm: str) -> bool:
    """Regional aur single-word titles ke spelling variations ko safely match karta hai."""
    if not query_norm or not candidate_norm:
        return False

    if query_norm == candidate_norm or query_norm in candidate_norm or candidate_norm in query_norm:
        return True

    score = fuzz.ratio(query_norm, candidate_norm) if fuzz else 0
    token_score = fuzz.token_sort_ratio(query_norm, candidate_norm) if fuzz else 0
    best_score = max(score, token_score)

    q_words = query_norm.split()
    c_words = candidate_norm.split()

    if len(q_words) == 1 and len(c_words) == 1:
        return best_score >= 75

    return best_score >= 65


def generate_search_queries(title: str):
    clean_title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
    words = clean_title.split()
    queries = []
    
    min_len = 2 if len(words) > 2 else 1
    for i in range(len(words), min_len - 1, -1):
        q = ' '.join(words[:i]).strip()
        if len(q) >= 3:
            queries.append(q)
            
    return list(dict.fromkeys(queries))


async def _find_poster_from_imdb(query: str, year: str = None):
    try:
        search_query = f"{query} {year}".strip() if year else query
        encoded_query = re.sub(r'\s+', '+', search_query)
        search_url = f"https://www.imdb.com/find?q={encoded_query}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept-Language': 'en-US,en;q=0.5'}

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(search_url, timeout=10) as resp:
                if resp.status != 200:
                    return None

                soup = BeautifulSoup(await resp.text(), 'html.parser')
                result_items = soup.select("li.ipc-metadata-list-summary-item")
                if not result_items:
                    return None

                for item in result_items[:5]:
                    title_elem = item.select_one("a.ipc-metadata-list-summary-item__t")
                    if not title_elem or not title_elem.get('href'):
                        continue

                    found_title = title_elem.get_text(strip=True).lower()
                    query_norm = query.lower().strip()

                    if not _is_title_match(query_norm, found_title):
                        continue

                    if year:
                        year_elem = item.select_one("span.ipc-metadata-list-summary-item__li")
                        if year_elem:
                            item_year = re.search(r'\b(19\d{2}|20\d{2})\b', year_elem.get_text(strip=True))
                            if item_year and abs(int(item_year.group(1)) - int(year)) > 1:
                                continue

                    movie_url = "https://www.imdb.com" + title_elem['href'].split('?')[0]
                    async with session.get(movie_url, timeout=10) as movie_resp:
                        if movie_resp.status != 200:
                            continue

                        movie_soup = BeautifulSoup(await movie_resp.text(), 'html.parser')
                        img_tag = movie_soup.select_one('div[data-testid="hero-media__poster"] img.ipc-image')

                        if img_tag and img_tag.get('src'):
                            return img_tag['src'].split('_V1_')[0] + "_V1_FMjpg_UX1000_.jpg"

    except Exception:
        return None

    return None


async def _find_poster_from_tmdb(query: str, year: str = None):
    if not getattr(Config, "TMDB_API_KEY", None):
        return None

    try:
        search_url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "api_key": Config.TMDB_API_KEY,
            "query": query,
            "include_adult": "false"
        }

        if year:
            params['year'] = str(year)
            params['primary_release_year'] = str(year)

        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                results = data.get('results', [])

                if results:
                    query_norm = query.lower().strip()

                    for result in results[:10]:
                        title_match = (result.get('title') or result.get('name') or "").lower().strip()
                        original_title = (result.get('original_title') or result.get('original_name') or "").lower().strip()
                        result_year = (result.get('release_date') or result.get('first_air_date') or "")[:4]

                        if year and result_year:
                            try:
                                if abs(int(year) - int(result_year)) > 1:
                                    continue
                            except ValueError:
                                pass

                        if _is_title_match(query_norm, title_match) or _is_title_match(query_norm, original_title):
                            if result.get("poster_path"):
                                return f"https://image.tmdb.org/t/p/original{result['poster_path']}"

    except Exception:
        return None

    return None


async def get_poster(query: str, year: str = None):
    sanitized_query = query.replace('"', '').strip()
    sanitized_query = re.sub(r'\(\d{4}\)', '', sanitized_query).strip()
    sanitized_query = re.sub(r'\b(19|20)\d{2}\b', '', sanitized_query).strip()

    search_queries = generate_search_queries(sanitized_query)

    logger.info(f"Waterfall Search: Starting for '{sanitized_query}'. Queries: {search_queries} | Year: {year}")

    for sq in search_queries:
        logger.info(f"Trying query '{sq}'")

        # 1. IMDb First (Regional & Marathi/Indian movies ke liye best accuracy)
        poster = await _find_poster_from_imdb(sq, str(year) if year else None)
        if poster:
            logger.info(f"IMDb success for '{sq}' ({year})")
            return poster

        # 2. TMDb Fallback
        poster = await _find_poster_from_tmdb(sq, str(year) if year else None)
        if poster:
            logger.info(f"TMDB success for '{sq}' ({year})")
            return poster

    logger.warning(f"All poster attempts failed or rejected for '{query}'")
    return None
