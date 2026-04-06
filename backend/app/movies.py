import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w780"
DEFAULT_TIMEOUT_SECONDS = 20
REQUEST_RETRY_COUNT = 3
REQUEST_BACKOFF_FACTOR = 0.8
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


def get_tmdb_api_key():
    return (os.getenv("TMDB_API_KEY") or "").strip()


def normalize_country_code(country):
    raw = str(country or "").strip()
    if not raw:
        return ""

    if len(raw) == 2 and raw.isalpha():
        return raw.upper()

    return FALLBACK_COUNTRY_CODES.get(raw.casefold(), "")


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

    try:
        response = TMDB_SESSION.get(
            f"{TMDB_API_BASE}{path}",
            params=request_params,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        raise ValueError(
            "TMDB is temporarily unavailable or the network connection was interrupted. "
            "Please try again in a moment."
        ) from error


def fetch_tmdb_movie_genres():
    payload = tmdb_request("/genre/movie/list")
    genres = payload.get("genres") or []
    return {
        str(item.get("name") or "").strip().casefold(): item.get("id")
        for item in genres
        if item.get("id") and str(item.get("name") or "").strip()
    }


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
        base_params["with_origin_country"] = country_code

    for page in range(1, 4):
        payload = tmdb_request("/discover/movie", {**base_params, "page": page})
        for item in payload.get("results") or []:
            movie_id = item.get("id")
            if not movie_id or movie_id in seen_ids:
                continue
            serialized = serialize_tmdb_movie(item)
            if not serialized["title"]:
                continue
            seen_ids.add(movie_id)
            candidates.append(serialized)
            if len(candidates) >= limit:
                return candidates

    fallback_payload = tmdb_request(
        "/movie/popular",
        {"page": 1, **({"region": country_code} if country_code else {})},
    )
    for item in fallback_payload.get("results") or []:
        movie_id = item.get("id")
        if not movie_id or movie_id in seen_ids:
            continue
        serialized = serialize_tmdb_movie(item)
        if not serialized["title"]:
            continue
        seen_ids.add(movie_id)
        candidates.append(serialized)
        if len(candidates) >= limit:
            break

    if not candidates:
        raise ValueError("TMDB could not return enough movies right now.")

    return candidates
