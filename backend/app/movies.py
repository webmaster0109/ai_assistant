import os
import re
import json
import hashlib

import requests
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w780"
DEFAULT_TIMEOUT_SECONDS = 20
REQUEST_RETRY_COUNT = 3
REQUEST_BACKOFF_FACTOR = 0.8
TMDB_CACHE_TTL_SECONDS = 60 * 60 * 6
FALLBACK_COUNTRY_CODES = {
    "australia": "AU",
    "bangladesh": "BD",
    "canada": "CA",
    "china": "CN",
    "france": "FR",
    "germany": "DE",
    "india": "IN",
    "indonesia": "ID",
    "italy": "IT",
    "japan": "JP",
    "korea": "KR",
    "nepal": "NP",
    "pakistan": "PK",
    "spain": "ES",
    "uk": "GB",
    "united kingdom": "GB",
    "united states": "US",
    "usa": "US",
}
FALLBACK_GENRE_IDS = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "science fiction": 878,
    "thriller": 53,
    "war": 10752,
}

YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
BETWEEN_YEARS_PATTERN = re.compile(
    r"\b(?:between|from)\s+((?:19|20)\d{2})\s+(?:and|to|-)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
AFTER_YEAR_PATTERN = re.compile(
    r"\b(?:after|newer than|later than|post)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
SINCE_YEAR_PATTERN = re.compile(
    r"\b(?:since|from|starting|starting from|onward from|onwards from)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
BEFORE_YEAR_PATTERN = re.compile(
    r"\b(?:before|older than|earlier than|pre)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
ONWARDS_PATTERN = re.compile(r"\b((?:19|20)\d{2})\s+onwards\b", re.IGNORECASE)
IN_YEAR_PATTERN = re.compile(r"\bin\s+((?:19|20)\d{2})\b", re.IGNORECASE)


def build_tmdb_session():
    retry = Retry(
        total=REQUEST_RETRY_COUNT,
        connect=REQUEST_RETRY_COUNT,
        read=REQUEST_RETRY_COUNT,
        status=REQUEST_RETRY_COUNT,
        backoff_factor=REQUEST_BACKOFF_FACTOR,
        allowed_methods=frozenset({"GET"}),
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


TMDB_SESSION = build_tmdb_session()


def build_tmdb_cache_key(path, params=None):
    payload = json.dumps(
        {
            "path": path,
            "params": params or {},
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"tmdb:{digest}"


def get_tmdb_api_key():
    return (os.getenv("TMDB_API_KEY") or "").strip()


def normalize_country_code(country):
    raw = str(country or "").strip()
    if not raw:
        return ""

    if len(raw) == 2 and raw.isalpha():
        return raw.upper()

    return FALLBACK_COUNTRY_CODES.get(raw.casefold(), "")


def extract_release_year_filters(extra_preferences):
    text = str(extra_preferences or "").strip()
    if not text:
        return {"year_gte": None, "year_lte": None}

    between_match = BETWEEN_YEARS_PATTERN.search(text)
    if between_match:
        start_year = int(between_match.group(1))
        end_year = int(between_match.group(2))
        if start_year > end_year:
            start_year, end_year = end_year, start_year
        return {"year_gte": start_year, "year_lte": end_year}

    after_match = AFTER_YEAR_PATTERN.search(text)
    if after_match:
        return {"year_gte": int(after_match.group(1)) + 1, "year_lte": None}

    since_match = SINCE_YEAR_PATTERN.search(text) or ONWARDS_PATTERN.search(text)
    if since_match:
        return {"year_gte": int(since_match.group(1)), "year_lte": None}

    before_match = BEFORE_YEAR_PATTERN.search(text)
    if before_match:
        return {"year_gte": None, "year_lte": int(before_match.group(1)) - 1}

    in_year_match = IN_YEAR_PATTERN.search(text)
    if in_year_match:
        year = int(in_year_match.group(1))
        return {"year_gte": year, "year_lte": year}

    explicit_years = [int(match.group(0)) for match in YEAR_PATTERN.finditer(text)]
    if len(explicit_years) == 1:
        year = explicit_years[0]
        return {"year_gte": year, "year_lte": year}

    return {"year_gte": None, "year_lte": None}


def movie_matches_year_filters(movie, year_gte=None, year_lte=None):
    if year_gte is None and year_lte is None:
        return True

    try:
        year = int(str(movie.get("year") or "").strip())
    except (TypeError, ValueError):
        return False

    if year_gte is not None and year < year_gte:
        return False
    if year_lte is not None and year > year_lte:
        return False
    return True


def tmdb_request(path, params=None):
    api_key = get_tmdb_api_key()
    if not api_key:
        raise ValueError("TMDB API key is not configured.")

    request_params = {
        "api_key": api_key,
        "language": "en-US",
    }
    if params:
        request_params.update(params)

    cache_key = build_tmdb_cache_key(path, request_params)
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return cached_payload

    try:
        response = TMDB_SESSION.get(
            f"{TMDB_API_BASE}{path}",
            params=request_params,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        cache.set(cache_key, payload, TMDB_CACHE_TTL_SECONDS)
        return payload
    except requests.RequestException as error:
        raise ValueError(
            "TMDB is temporarily unavailable or the network connection was interrupted. "
            "Please try again in a moment."
        ) from error


def fetch_tmdb_movie_genres():
    try:
        payload = tmdb_request("/genre/movie/list")
    except ValueError:
        return FALLBACK_GENRE_IDS
    genres = payload.get("genres") or []
    genre_map = {
        str(item.get("name") or "").strip().casefold(): item.get("id")
        for item in genres
        if item.get("id") and str(item.get("name") or "").strip()
    }
    return genre_map or FALLBACK_GENRE_IDS


def resolve_genre_id(genre_name):
    raw = str(genre_name or "").strip()
    if not raw:
        return None

    genre_map = fetch_tmdb_movie_genres()
    normalized = raw.casefold()
    if normalized in genre_map:
        return genre_map[normalized]

    for name, genre_id in genre_map.items():
        if normalized in name or name in normalized:
            return genre_id
    return None


def serialize_tmdb_movie(item):
    release_date = str(item.get("release_date") or "").strip()
    poster_path = str(item.get("poster_path") or "").strip()
    backdrop_path = str(item.get("backdrop_path") or "").strip()
    return {
        "id": item.get("id"),
        "title": str(item.get("title") or "").strip(),
        "year": release_date[:4] if len(release_date) >= 4 else "",
        "rating": round(float(item.get("vote_average") or 0), 1),
        "vote_count": int(item.get("vote_count") or 0),
        "overview": str(item.get("overview") or "").strip(),
        "original_language": str(item.get("original_language") or "").strip(),
        "poster_url": f"{TMDB_POSTER_BASE}{poster_path}" if poster_path else "",
        "backdrop_url": f"{TMDB_BACKDROP_BASE}{backdrop_path}" if backdrop_path else "",
        "imdb_url": "",
        "trailer_url": "",
    }


def fetch_tmdb_movie_details(movie_id):
    try:
        return tmdb_request(f"/movie/{movie_id}")
    except ValueError:
        return {}


def movie_matches_country_filter(details, country_code):
    normalized_code = str(country_code or "").strip().upper()
    if not normalized_code:
        return True

    payload = details or {}
    production_countries = payload.get("production_countries") or []
    for item in production_countries:
        if str(item.get("iso_3166_1") or "").strip().upper() == normalized_code:
            return True

    origin_countries = payload.get("origin_country") or []
    for code in origin_countries:
        if str(code or "").strip().upper() == normalized_code:
            return True

    return False


def fetch_tmdb_movie_extras(movie_id):
    try:
        payload = tmdb_request(
            f"/movie/{movie_id}",
            {"append_to_response": "external_ids,videos"},
        )
    except ValueError:
        return {
            "imdb_url": "",
            "trailer_url": "",
        }

    imdb_id = str((payload.get("external_ids") or {}).get("imdb_id") or "").strip()
    videos = (payload.get("videos") or {}).get("results") or []

    trailer = next(
        (
            item for item in videos
            if str(item.get("site") or "").strip().lower() == "youtube"
            and str(item.get("type") or "").strip().lower() == "trailer"
            and item.get("key")
        ),
        None,
    )
    if trailer is None:
        trailer = next(
            (
                item for item in videos
                if str(item.get("site") or "").strip().lower() == "youtube"
                and item.get("key")
            ),
            None,
        )

    trailer_key = str((trailer or {}).get("key") or "").strip()

    return {
        "imdb_url": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "",
        "trailer_url": f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else "",
    }


def fetch_tmdb_movie_candidates(mood, genre, country, extra_preferences="", limit=24):
    genre_id = resolve_genre_id(genre)
    country_code = normalize_country_code(country)
    release_filters = extract_release_year_filters(extra_preferences)
    year_gte = release_filters["year_gte"]
    year_lte = release_filters["year_lte"]
    seen_ids = set()
    candidates = []

    base_params = {
        "include_adult": "false",
        "include_video": "false",
        "sort_by": "vote_average.desc",
        "vote_count.gte": 180,
    }
    if genre_id:
        base_params["with_genres"] = genre_id
    if country_code:
        base_params["region"] = country_code
    if year_gte is not None:
        base_params["primary_release_date.gte"] = f"{year_gte}-01-01"
    if year_lte is not None:
        base_params["primary_release_date.lte"] = f"{year_lte}-12-31"

    discover_pages = 6 if country_code or year_gte or year_lte else 3

    for page in range(1, discover_pages + 1):
        try:
            payload = tmdb_request("/discover/movie", {**base_params, "page": page})
        except ValueError:
            continue
        for item in payload.get("results") or []:
            movie_id = item.get("id")
            if not movie_id or movie_id in seen_ids:
                continue
            serialized = serialize_tmdb_movie(item)
            if not serialized["title"]:
                continue
            if not movie_matches_year_filters(serialized, year_gte=year_gte, year_lte=year_lte):
                continue
            if country_code:
                details = fetch_tmdb_movie_details(movie_id)
                if not movie_matches_country_filter(details, country_code):
                    continue
            seen_ids.add(movie_id)
            candidates.append(serialized)
            if len(candidates) >= limit:
                return candidates

    try:
        fallback_payload = tmdb_request(
            "/movie/popular",
            {"page": 1, **({"region": country_code} if country_code else {})},
        )
    except ValueError:
        fallback_payload = {"results": []}

    for item in fallback_payload.get("results") or []:
        movie_id = item.get("id")
        if not movie_id or movie_id in seen_ids:
            continue
        serialized = serialize_tmdb_movie(item)
        if not serialized["title"]:
            continue
        if not movie_matches_year_filters(serialized, year_gte=year_gte, year_lte=year_lte):
            continue
        if country_code:
            details = fetch_tmdb_movie_details(movie_id)
            if not movie_matches_country_filter(details, country_code):
                continue
        seen_ids.add(movie_id)
        candidates.append(serialized)
        if len(candidates) >= limit:
            break

    if not candidates:
        raise ValueError(
            "No matching movies were found for the selected country and release filters right now. "
            "Try a broader genre, country, or year preference."
        )

    return candidates
