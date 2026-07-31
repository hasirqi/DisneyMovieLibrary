#!/usr/bin/env python3
"""Enrich verified movie posters through Wikidata TMDB IDs.

The script never guesses by title. It follows each catalog record's Wikidata
entity to property P4947 (TMDB movie ID), then reads the first TMDB poster image
from that movie's public page. Results are cached and written to both offline
catalog formats.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import time
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


def write_catalog(movies: list[dict[str, Any]]) -> None:
    payload = json.dumps(movies, ensure_ascii=False, separators=(",", ":"))
    JSON_PATH.write_text(payload + "\n", encoding="utf-8")
    JS_PATH.write_text("window.__LOCAL_MOVIES__=" + payload + ";\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=250, help="maximum missing posters to attempt")
    parser.add_argument("--studios", nargs="+", default=DEFAULT_STUDIOS, help="studio priority order")
    parser.add_argument("--delay", type=float, default=0.12, help="delay between TMDB page requests")
    args = parser.parse_args()

    movies: list[dict[str, Any]] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache: dict[str, str] = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    priority = {studio: index for index, studio in enumerate(args.studios)}
    candidates = [
        movie for movie in movies
        if not movie.get("poster_url") and movie.get("wikidata_id") and movie.get("studio") in priority
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
        if movie_id not in cache:
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

    write_catalog(movies)
    print(f"Attempted {attempted}; added {updated} posters; total coverage {sum(bool(x.get('poster_url')) for x in movies)}/{len(movies)}")


if __name__ == "__main__":
    main()
