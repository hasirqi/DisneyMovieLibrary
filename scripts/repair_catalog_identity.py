#!/usr/bin/env python3
"""Link same-film aliases without collapsing sequels, remakes, or raw records.

Identity requires a normalized English title *and* release year. Records are
never deleted: secondary aliases receive duplicate_of and remain in the raw
3,534-record archive, while the frontend displays one enriched primary record.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "movies.json"
JS_PATH = ROOT / "data" / "movies.js"


def canonical_title(value: str) -> str:
    title = value.casefold().strip()
    title = re.sub(r"\s*\((?:\d{4}\s+)?(?:film|movie)\)\s*$", "", title)
    title = re.sub(r"\s*\((?:american|british|disney|animated|live-action)[^)]*film\)\s*$", "", title)
    return re.sub(r"[^a-z0-9]+", "", title)


def catalog_id(movie: dict[str, Any], index: int) -> str:
    seed = f"{movie.get('title_en')}|{movie.get('year')}|{movie.get('source_url')}|{index}"
    return "film-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def quality(movie: dict[str, Any]) -> int:
    score = 0
    if re.search(r"\((?:\d{4}\s+)?film\)$", movie.get("title_en", ""), re.I): score += 8
    if movie.get("tmdb_id"): score += 6
    if movie.get("wikidata_id"): score += 3
    if movie.get("poster_url"): score += 2
    if movie.get("summary_en") and "Disney catalog" not in movie["summary_en"]: score += 2
    if movie.get("director_en") not in (None, "", "资料暂缺", "Not available"): score += 1
    return score


def copy_if_better(primary: dict[str, Any], alias: dict[str, Any], field: str) -> None:
    missing = primary.get(field) in (None, "", 0, "—", "资料暂缺", "Not available")
    if missing and alias.get(field) not in (None, "", 0, "—", "资料暂缺", "Not available"):
        primary[field] = alias[field]


def write_catalog(movies: list[dict[str, Any]]) -> None:
    payload = json.dumps(movies, ensure_ascii=False, separators=(",", ":"))
    JSON_PATH.write_text(payload + "\n", encoding="utf-8")
    JS_PATH.write_text("window.__LOCAL_MOVIES__=" + payload + ";\n", encoding="utf-8")


def main() -> None:
    movies: list[dict[str, Any]] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    # Correct two known cross-year collisions before grouping. Release year is
    # decisive: the 2019 remake and the 1994 animation are separate films;
    # The Avengers detail page used an early-premiere year and belongs to 2012.
    for movie in movies:
        if movie.get("title_en") == "The Lion King" and movie.get("year") == 2019:
            identity_was_wrong = movie.get("wikidata_id") != "Q27044293" or str(movie.get("tmdb_id")) != "420818"
            movie["wikidata_id"] = "Q27044293"
            movie["tmdb_id"] = "420818"
            if identity_was_wrong:
                movie.pop("source_url", None)
                for field in ("poster_url", "poster_source", "box_office_amount", "box_office_currency",
                              "box_office_scope", "box_office_source"):
                    movie.pop(field, None)
        if movie.get("title_en") == "The Avengers (2012 film)" and movie.get("year") == 2011:
            movie["year"] = 2012
        # Normalize obsolete planned years and a regional-release split. These
        # pairs resolve to the same TMDB film, so the older raw record becomes
        # an alias after grouping instead of masquerading as a separate sequel.
        if movie.get("title_en") == "Finding Dory" and movie.get("year") == 2015:
            movie["year"] = 2016
        if movie.get("title_en") == "The Good Dinosaur" and movie.get("year") == 2014:
            movie["year"] = 2015
        if movie.get("title_en") == "Born in China" and movie.get("year") == 2017:
            movie["year"] = 2016
    for index, movie in enumerate(movies):
        movie["catalog_id"] = catalog_id(movie, index)
        movie.pop("duplicate_of", None)
        movie.pop("alias_titles", None)

    # Connect records by either normalized title+year or the stronger
    # TMDB-movie-ID+year identity. The latter catches abbreviated aliases such
    # as "The Force Awakens" vs "Star Wars: The Force Awakens" without merging
    # remakes or sequels released in different years.
    parents = list(range(len(movies)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    identity_owner: dict[tuple[str, str, int], int] = {}
    for index, movie in enumerate(movies):
        year = int(movie.get("year") or 0)
        if not year:
            continue
        keys = [("title", canonical_title(movie.get("title_en", "")), year)]
        if movie.get("tmdb_id"):
            keys.append(("tmdb", str(movie["tmdb_id"]), year))
        for key in keys:
            if not key[1]:
                continue
            if key in identity_owner:
                union(index, identity_owner[key])
            else:
                identity_owner[key] = index

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, movie in enumerate(movies):
        groups[find(index)].append(movie)

    linked = 0
    for records in groups.values():
        if len(records) < 2:
            continue
        primary = max(records, key=lambda movie: (
            quality(movie),
            ":" in movie.get("title_en", ""),
            len(movie.get("title_en", "")),
        ))
        aliases = [movie for movie in records if movie is not primary]
        primary_original_title = primary.get("title_en", "")
        shared_tmdb = {str(movie["tmdb_id"]) for movie in records if movie.get("tmdb_id")}
        if len(shared_tmdb) == 1:
            preferred_title = max((movie.get("title_en", "") for movie in records), key=lambda title: (":" in title, len(title)))
            if ":" in preferred_title and ":" not in primary_original_title:
                primary["title_en"] = preferred_title
        primary["alias_titles"] = sorted(({
            title for movie in aliases
            for title in (movie.get("title_en", ""), movie.get("title_cn", "")) if title
        } | ({primary_original_title} if primary_original_title != primary.get("title_en") else set())) - {primary.get("title_en", "")})
        for alias in aliases:
            alias["duplicate_of"] = primary["catalog_id"]
            # The detailed film entity is authoritative for identity. Preserve
            # alias text, but correct IDs that previously pointed to a concept,
            # character, animated original, or another same-named work.
            for field in ("wikidata_id", "tmdb_id", "source_url"):
                if primary.get(field):
                    alias[field] = primary[field]
            for field in ("featured_rank", "poster_url", "poster_source", "summary_en", "summary_cn",
                          "director_en", "director_cn", "cast_en", "cast_cn", "runtime",
                          "box_office_amount", "box_office_currency", "box_office_scope", "box_office_source"):
                copy_if_better(primary, alias, field)
            linked += 1

    # Known future-film records inherited IDs from earlier installments. Keep
    # the films, but clear identity-dependent metadata until their own IDs are
    # available. Release years and sequel numbers remain distinct identities.
    future_bad_ids = {"Avatar 4", "Incredibles 3"}
    for movie in movies:
        if movie.get("title_en") not in future_bad_ids:
            continue
        for field in ("wikidata_id", "tmdb_id", "source_url", "poster_url", "poster_source",
                      "box_office_amount", "box_office_currency", "box_office_scope", "box_office_source"):
            movie.pop(field, None)

    write_catalog(movies)
    print(f"Linked {linked} secondary aliases; preserved {len(movies)} raw records")


if __name__ == "__main__":
    main()
