#!/usr/bin/env python3
"""Build the offline Disney film catalog from Wikimedia category and entity data.

The script intentionally uses only Python's standard library plus curl so it can
run in the same no-build-tool spirit as the website.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "movies.json"
JS_PATH = ROOT / "data" / "movies.js"
API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "DisneyMovieLibrary/2.0 (https://github.com/hasirqi/DisneyMovieLibrary)"

# Category order is also the duplicate-resolution priority. Specific labels are
# listed before broad distribution banners.
CATEGORIES = [
    ("迪士尼动画", "Walt Disney Animation Studios films"),
    ("迪士尼动画", "DisneyToon Studios animated films"),
    ("皮克斯", "Pixar animated films"),
    ("漫威", "Marvel Studios films"),
    ("星球大战", "Lucasfilm films"),
    ("纪录片", "Disneynature films"),
    ("纪录片", "National Geographic documentary films"),
    ("二十世纪影业", "20th Century Studios films"),
    ("二十世纪影业", "20th Century Fox films"),
    ("二十世纪影业", "Fox Searchlight Pictures films"),
    ("二十世纪影业", "Searchlight Pictures films"),
    ("真人电影", "Walt Disney Pictures films"),
    ("真人电影", "Touchstone Pictures films"),
    ("真人电影", "Hollywood Pictures films"),
    ("真人电影", "Disney Channel Original Movie films"),
]

FEATURED_POSTERS = [
    (("The Lion King", 1994), "https://image.tmdb.org/t/p/w500/sKCr78MXSLixwmZ8DyJLrpMsd15.jpg"),
    (("Toy Story", 1995), "https://image.tmdb.org/t/p/w500/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg"),
    (("Frozen", 2013), "https://image.tmdb.org/t/p/w500/itAKcobTYGpYT8Phwjd8c9hleTo.jpg"),
    (("Avengers: Endgame", 2019), "https://image.tmdb.org/t/p/w500/ulzhLuWrPK07P1YkdWQLZnQh1JL.jpg"),
    (("Coco", 2017), "https://image.tmdb.org/t/p/w500/6Ryitt95xrO8KXuqRGm1fUuNwqF.jpg"),
    (("Avatar", 2009), "https://image.tmdb.org/t/p/w500/gKY6q7SjCkAU6FqvqWybDYgUKIF.jpg"),
    (("Beauty and the Beast", 1991), "https://image.tmdb.org/t/p/w500/hUJ0UvQ5tgE2Z9WpfuduVSdiCiU.jpg"),
    (("Moana", 2016), "https://image.tmdb.org/t/p/w500/m5MDZOIFEFlxGiLuAzWzFSsWcye.jpg"),
    (("Black Panther", 2018), "https://image.tmdb.org/t/p/w500/uxzzxijgPIY7slzFvMotPv8wjKA.jpg"),
    (("Up", 2009), "https://image.tmdb.org/t/p/w500/mFvoEwSfLqbcWwFsDjQebn9bzFe.jpg"),
    (("Star Wars: A New Hope", 1977), "https://image.tmdb.org/t/p/w500/6FfCtAuVAW8XJjZ7eWeLibRLWTw.jpg"),
    (("Pirates of the Caribbean: The Curse of the Black Pearl", 2003), "https://image.tmdb.org/t/p/w500/poHwCZeWzJCShH7tOjg8RIoyjcw.jpg"),
]


def chunks(values: list[str], size: int = 40) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def api(params: dict[str, Any], retries: int = 4, endpoint: str = API) -> dict[str, Any]:
    form = {"format": "json", "formatversion": "2", **params}
    command = ["curl", "-fsSL", "--retry", "3", "-A", USER_AGENT]
    for key, value in form.items():
        command.extend(["--data-urlencode", f"{key}={value}"])
    command.append(endpoint)
    for attempt in range(retries):
        try:
            return json.loads(subprocess.check_output(command, text=True))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return {}


def category_pages(category: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    continuation: dict[str, Any] = {}
    while True:
        payload = api({
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmnamespace": "0",
            "cmtype": "page",
            "cmlimit": "max",
            **continuation,
        })
        members.extend(payload.get("query", {}).get("categorymembers", []))
        continuation = payload.get("continue", {})
        if not continuation:
            break
    return members


def page_metadata(titles: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for batch in chunks(titles):
        payload = api({
            "action": "query",
            "prop": "pageprops|langlinks|extracts|pageimages",
            "titles": "|".join(batch),
            "redirects": "1",
            "lllang": "zh",
            "lllimit": "1",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": "2",
            "piprop": "thumbnail",
            "pithumbsize": "500",
        })
        for page in payload.get("query", {}).get("pages", []):
            requested = page.get("title", "")
            result[requested] = page
        time.sleep(0.04)
    return result


def wikidata_entities(ids: list[str], props: str = "labels|claims") -> dict[str, Any]:
    entities: dict[str, Any] = {}
    for batch in chunks(ids, 45):
        payload = api({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": props,
            "languages": "zh|en",
            "languagefallback": "1",
        }, endpoint=WIKIDATA_API)
        entities.update(payload.get("entities", {}))
        time.sleep(0.04)
    return entities


def claim_ids(entity: dict[str, Any], prop: str) -> list[str]:
    found: list[str] = []
    for statement in entity.get("claims", {}).get(prop, []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            found.append(value["id"])
    return found


def release_year(entity: dict[str, Any], fallback_text: str) -> int:
    years: list[int] = []
    for statement in entity.get("claims", {}).get("P577", []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        match = re.match(r"[+-](\d{4,})-", str(value.get("time", "")))
        if match:
            year = int(match.group(1))
            if 1880 <= year <= 2100:
                years.append(year)
    if years:
        return min(years)
    match = re.search(r"\b(19|20)\d{2}\b", fallback_text)
    return int(match.group()) if match else 0


def label(entity: dict[str, Any]) -> str:
    labels = entity.get("labels", {})
    return (labels.get("zh") or labels.get("en") or {}).get("value", "")


def normalize_key(title: str, year: int) -> str:
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.casefold())
    return f"{cleaned}:{year or 'unknown'}"


def build() -> list[dict[str, Any]]:
    curated = [
        movie for movie in json.loads(JSON_PATH.read_text(encoding="utf-8"))
        if not movie.get("source")
    ]
    assignments: dict[str, str] = {}
    page_ids: dict[str, int] = {}
    for studio, category in CATEGORIES:
        members = category_pages(category)
        print(f"{category}: {len(members)}")
        for member in members:
            title = member["title"]
            if title.startswith(("List of ", "Lists of ")):
                continue
            assignments.setdefault(title, studio)
            page_ids[title] = member["pageid"]

    titles = list(assignments)
    print(f"Unique English Wikipedia pages: {len(titles)}")
    pages = page_metadata(titles)
    qids = sorted({
        page.get("pageprops", {}).get("wikibase_item")
        for page in pages.values()
        if page.get("pageprops", {}).get("wikibase_item")
    })
    entities = wikidata_entities(qids)
    director_ids = sorted({
        director
        for entity in entities.values()
        for director in claim_ids(entity, "P57")
    })
    directors = wikidata_entities(director_ids, "labels")

    generated: list[dict[str, Any]] = []
    for title_en in titles:
        page = pages.get(title_en, {})
        qid = page.get("pageprops", {}).get("wikibase_item", "")
        entity = entities.get(qid, {})
        wikipedia_cn = next((x.get("title", "") for x in page.get("langlinks", []) if x.get("title")), "")
        wikidata_cn = entity.get("labels", {}).get("zh", {}).get("value", "")
        title_cn = wikipedia_cn or wikidata_cn or title_en
        year = release_year(entity, page.get("extract", ""))
        director_names = [label(directors.get(item, {})) for item in claim_ids(entity, "P57")]
        summary = re.sub(r"\s+", " ", page.get("extract", "")).strip()
        generated.append({
            "title_cn": title_cn,
            "title_en": title_en,
            "year": year,
            "studio": assignments[title_en],
            "poster_url": page.get("thumbnail", {}).get("source", ""),
            "summary": summary or f"《{title_en}》的百科资料条目。",
            "director": "、".join(x for x in director_names if x) or "资料暂缺",
            "cast": "资料暂缺",
            "rating": 0,
            "runtime": "—",
            "source": "Wikipedia / Wikidata",
            "source_url": f"https://en.wikipedia.org/?curid={page_ids[title_en]}",
            "wikidata_id": qid,
            "title_cn_source": "wikipedia" if wikipedia_cn else "wikidata" if wikidata_cn else "english_fallback",
        })

    # Preserve the hand-curated Chinese entries and summaries for well-known
    # films, then add the larger encyclopedia catalog around them.
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for movie in [*curated, *generated]:
        key = normalize_key(movie.get("title_en") or movie["title_cn"], int(movie.get("year") or 0))
        if key in seen:
            continue
        seen.add(key)
        merged.append(movie)
    merged.sort(key=lambda item: (-(int(item.get("year") or 0)), item.get("title_en", "")))
    return merged


def write_catalog(movies: list[dict[str, Any]]) -> None:
    payload = json.dumps(movies, ensure_ascii=False, separators=(",", ":"))
    JSON_PATH.write_text(payload + "\n", encoding="utf-8")
    JS_PATH.write_text(
        "window.__LOCAL_MOVIES__=" + payload + ";\n",
        encoding="utf-8",
    )


def apply_featured_posters(movies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    featured = {key: (rank, url) for rank, (key, url) in enumerate(FEATURED_POSTERS, 1)}
    for movie in movies:
        key = (movie.get("title_en", ""), int(movie.get("year") or 0))
        if key in featured:
            rank, url = featured[key]
            movie["poster_url"] = url
            movie["featured_rank"] = rank
        else:
            movie.pop("featured_rank", None)
    return movies


if __name__ == "__main__":
    catalog = apply_featured_posters(build())
    write_catalog(catalog)
    print(f"Wrote {len(catalog)} unique titles")
