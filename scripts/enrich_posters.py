#!/usr/bin/env python3
"""Enrich verified movie posters through Wikidata TMDB IDs.

The default path never guesses by title. An optional strict fallback accepts a
TMDB search result only when its normalized English title and release year both
exactly match the catalog record. Results are cached and written to both
offline catalog formats.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "movies.json"
JS_PATH = ROOT / "data" / "movies.js"
CACHE_PATH = ROOT / "data" / "poster_cache.json"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "DisneyMovieLibrary/2.0 (https://github.com/hasirqi/DisneyMovieLibrary)"
DEFAULT_STUDIOS = ["迪士尼动画", "皮克斯", "漫威", "星球大战", "纪录片", "真人电影", "二十世纪影业"]


def chunks(values: list[str], size: int = 45) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def curl(url: str, retries: int = 3) -> str:
    command = ["curl", "-fsSL", "--retry", str(retries), "-A", USER_AGENT, url]
    return subprocess.check_output(command, text=True)


def tmdb_ids(qids: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for batch in chunks(qids):
        ids = "%7C".join(batch)
        url = f"{WIKIDATA_API}?action=wbgetentities&ids={ids}&props=claims&format=json"
        payload = json.loads(curl(url))
        for qid, entity in payload.get("entities", {}).items():
            statements = entity.get("claims", {}).get("P4947", [])
            for statement in statements:
                value = statement.get("mainsnak", {}).get("datavalue", {}).get("value")
                if value:
                    found[qid] = str(value)
                    break
        time.sleep(0.08)
    return found


def poster_from_tmdb(movie_id: str) -> str:
    page = curl(f"https://www.themoviedb.org/movie/{movie_id}")
    matches = re.findall(
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
        page,
        flags=re.IGNORECASE,
    )
    for value in matches:
        url = html.unescape(value)
        if "/t/p/w500/" in url and re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", url, re.IGNORECASE):
            return url.replace("https://media.themoviedb.org/", "https://image.tmdb.org/")
    return ""


def normalized_title(value: str) -> str:
    value = re.sub(r"\s*\((?:\d{4}\s+)?(?:film|movie)\)\s*$", "", value, flags=re.IGNORECASE)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def strict_tmdb_match(title: str, year: int) -> tuple[str, str]:
    """Return TMDB ID and poster only for an exact normalized title/year match."""
    query = urllib.parse.quote_plus(title)
    search = curl(f"https://www.themoviedb.org/search/movie?query={query}")
    movie_ids = list(dict.fromkeys(re.findall(r'href="/movie/(\d+)(?:-[^"?#]*)?', search)))[:8]
    expected = normalized_title(title)
    for movie_id in movie_ids:
        try:
            page = curl(f"https://www.themoviedb.org/movie/{movie_id}")
        except subprocess.CalledProcessError:
            continue
        title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', page, re.IGNORECASE)
        year_match = re.search(r'<span\s+class="tag release_date">\((\d{4})\)</span>', page, re.IGNORECASE)
        if not title_match or not year_match:
            continue
        actual_title = html.unescape(title_match.group(1))
        if normalized_title(actual_title) != expected or int(year_match.group(1)) != year:
            continue
        poster = poster_from_tmdb(movie_id)
        if poster:
            return movie_id, poster
    return "", ""


def write_catalog(movies: list[dict[str, Any]]) -> None:
    payload = json.dumps(movies, ensure_ascii=False, separators=(",", ":"))
    JSON_PATH.write_text(payload + "\n", encoding="utf-8")
    JS_PATH.write_text("window.__LOCAL_MOVIES__=" + payload + ";\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=250, help="maximum missing posters to attempt")
    parser.add_argument("--studios", nargs="+", default=DEFAULT_STUDIOS, help="studio priority order")
    parser.add_argument("--delay", type=float, default=0.12, help="delay between TMDB page requests")
    parser.add_argument("--retry-empty", action="store_true", help="retry cached empty TMDB responses")
    parser.add_argument(
        "--strict-title-year-fallback",
        action="store_true",
        help="search TMDB only when both normalized English title and release year match exactly",
    )
    args = parser.parse_args()

    movies: list[dict[str, Any]] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache: dict[str, str] = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    priority = {studio: index for index, studio in enumerate(args.studios)}
    candidates = [
        movie for movie in movies
        if not movie.get("duplicate_of")
        and not movie.get("poster_url")
        and movie.get("wikidata_id")
        and movie.get("studio") in priority
    ]
    candidates.sort(key=lambda movie: (
        priority[movie["studio"]],
        -(int(movie.get("year") or 0)),
        movie.get("title_en", ""),
    ))
    candidates = candidates[:max(0, args.limit)]
    ids = tmdb_ids(sorted({movie["wikidata_id"] for movie in candidates}))

    updated = 0
    attempted = 0
    for movie in candidates:
        qid = movie["wikidata_id"]
        movie_id = ids.get(qid)
        if not movie_id:
            continue
        attempted += 1
        if movie_id not in cache or (args.retry_empty and not cache[movie_id]):
            try:
                cache[movie_id] = poster_from_tmdb(movie_id)
            except subprocess.CalledProcessError:
                cache[movie_id] = ""
            CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            time.sleep(args.delay)
        poster = cache[movie_id]
        if poster:
            movie["poster_url"] = poster
            movie["poster_source"] = "TMDB"
            movie["tmdb_id"] = movie_id
            updated += 1
            print(f"+ {movie['studio']} | {movie['title_en']} ({movie.get('year') or '?'})")

    if args.strict_title_year_fallback:
        unresolved = [
            movie for movie in movies
            if not movie.get("duplicate_of")
            and not movie.get("poster_url")
            and int(movie.get("year") or 0) > 0
        ]
        for movie in unresolved:
            try:
                movie_id, poster = strict_tmdb_match(movie.get("title_en", ""), int(movie["year"]))
            except subprocess.CalledProcessError:
                movie_id, poster = "", ""
            if poster:
                movie["poster_url"] = poster
                movie["poster_source"] = "TMDB_EXACT_TITLE_YEAR"
                movie["tmdb_id"] = movie_id
                cache[movie_id] = poster
                updated += 1
                print(f"+ exact title/year | {movie['title_en']} ({movie['year']})")
            time.sleep(args.delay)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_catalog(movies)
    primary = [movie for movie in movies if not movie.get("duplicate_of")]
    print(f"Attempted {attempted}; added {updated} posters; primary coverage {sum(bool(x.get('poster_url')) for x in primary)}/{len(primary)}")


if __name__ == "__main__":
    main()
