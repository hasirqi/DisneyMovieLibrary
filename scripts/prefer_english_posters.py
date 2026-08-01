#!/usr/bin/env python3
"""Prefer TMDB posters explicitly tagged as English.

The catalog's existing TMDB movie IDs remain the identity authority. For each
ID, the script reads TMDB's English-filtered poster gallery and selects its
first ranked English image. Missing English galleries leave current artwork
unchanged.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "movies.json"
JS_PATH = ROOT / "data" / "movies.js"
CACHE_PATH = ROOT / "data" / "english_poster_cache.json"
USER_AGENT = "DisneyMovieLibrary/2.0 (https://github.com/hasirqi/DisneyMovieLibrary)"


def english_poster(movie_id: str) -> str:
    url = f"https://www.themoviedb.org/movie/{movie_id}/images/posters?image_language=en&language=en-US"
    page = subprocess.check_output(
        ["curl", "-fsSL", "--retry", "2", "--max-time", "25", "-A", USER_AGENT, url],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    matches = re.findall(
        r'https://media\.themoviedb\.org/t/p/w220_and_h330_face/([A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp))',
        page,
        flags=re.IGNORECASE,
    )
    if not matches:
        return ""
    return f"https://image.tmdb.org/t/p/w500/{matches[0]}"


def write_catalog(movies: list[dict[str, Any]]) -> None:
    payload = json.dumps(movies, ensure_ascii=False, separators=(",", ":"))
    JSON_PATH.write_text(payload + "\n", encoding="utf-8")
    JS_PATH.write_text("window.__LOCAL_MOVIES__=" + payload + ";\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6, help="parallel TMDB requests")
    parser.add_argument("--limit", type=int, default=0, help="maximum uncached IDs; 0 means all")
    parser.add_argument("--retry-empty", action="store_true", help="retry cached IDs without an English poster")
    args = parser.parse_args()

    movies: list[dict[str, Any]] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache: dict[str, str] = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    primary_ids = sorted({
        str(movie["tmdb_id"])
        for movie in movies
        if not movie.get("duplicate_of") and movie.get("tmdb_id") and movie.get("poster_url")
    }, key=int)
    pending = [movie_id for movie_id in primary_ids if movie_id not in cache or (args.retry_empty and not cache[movie_id])]
    if args.limit > 0:
        pending = pending[:args.limit]

    def fetch(movie_id: str) -> tuple[str, str]:
        try:
            return movie_id, english_poster(movie_id)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return movie_id, ""

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for movie_id, poster in executor.map(fetch, pending):
            cache[movie_id] = poster
            completed += 1
            if completed % 100 == 0:
                print(f"Checked {completed}/{len(pending)} TMDB movies", flush=True)

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    updated = 0
    for movie in movies:
        movie_id = str(movie.get("tmdb_id") or "")
        poster = cache.get(movie_id, "")
        if poster:
            if movie.get("poster_url") != poster:
                movie["poster_url"] = poster
                updated += 1
            movie["poster_source"] = "TMDB_ENGLISH"

    write_catalog(movies)
    found = sum(bool(cache.get(movie_id)) for movie_id in primary_ids)
    print(f"Checked {len(pending)} new IDs; English posters {found}/{len(primary_ids)}; updated {updated} records")


if __name__ == "__main__":
    main()
