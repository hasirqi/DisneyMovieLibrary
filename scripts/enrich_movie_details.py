#!/usr/bin/env python3
"""Enrich directors, principal cast and bilingual summaries from Wikimedia."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from enrich_chinese_titles import google_translate
from sync_wikimedia import JSON_PATH, WIKIDATA_API, api, chunks, write_catalog

ROOT = Path(__file__).resolve().parents[1]
PEOPLE_CACHE = ROOT / "data" / "people_labels.json"
SUMMARY_CACHE = ROOT / "data" / "chinese_summaries.json"
MOVIE_CREDITS_CACHE = ROOT / "data" / "movie_credits.json"
MAX_CAST = 6


def resolve_missing_wikidata(movies: list[dict]) -> None:
    missing = [movie for movie in movies if not movie.get("wikidata_id")]

    def resolve(movie: dict) -> tuple[dict, dict]:
        query = f'"{movie["title_en"]}" {movie.get("year", "")} film'
        payload = api({
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrnamespace": "0", "gsrlimit": "3",
            "prop": "pageprops|extracts", "exintro": "1", "explaintext": "1", "exsentences": "2",
        })
        pages = payload.get("query", {}).get("pages", [])
        page = next((item for item in pages if item.get("pageprops", {}).get("wikibase_item")), {})
        return movie, page

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(resolve, movie) for movie in missing]
        for number, future in enumerate(as_completed(futures), 1):
            movie, page = future.result()
            qid = page.get("pageprops", {}).get("wikibase_item", "")
            if qid:
                movie["wikidata_id"] = qid
                movie["source"] = movie.get("source") or "Wikipedia / Wikidata"
                movie["source_url"] = movie.get("source_url") or f'https://en.wikipedia.org/?curid={page.get("pageid")}'
                extract = re.sub(r"\s+", " ", page.get("extract", "")).strip()
                if extract:
                    movie["summary_en"] = extract
            print(f"Resolve curated films: {number}/{len(missing)}", flush=True)


def statement_ids(entity: dict, prop: str, limit: int | None = None) -> list[str]:
    values = []
    statements = entity.get("claims", {}).get(prop, [])
    statements = sorted(statements, key=lambda item: 0 if item.get("rank") == "preferred" else 1)
    for statement in statements:
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id") and value["id"] not in values:
            values.append(value["id"])
            if limit and len(values) >= limit:
                break
    return values


def load_movie_credits(qids: list[str]) -> dict[str, dict]:
    result = json.loads(MOVIE_CREDITS_CACHE.read_text(encoding="utf-8")) if MOVIE_CREDITS_CACHE.exists() else {}
    missing = [qid for qid in qids if qid not in result]
    for number, batch in enumerate(chunks(missing, 45), 1):
        payload = api({
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "claims", "languages": "en",
        }, endpoint=WIKIDATA_API)
        for qid, entity in payload.get("entities", {}).items():
            directors = statement_ids(entity, "P57")
            cast = statement_ids(entity, "P161", MAX_CAST)
            if len(cast) < MAX_CAST:
                for person in statement_ids(entity, "P725", MAX_CAST):
                    if person not in cast:
                        cast.append(person)
                    if len(cast) >= MAX_CAST:
                        break
            result[qid] = {"directors": directors, "cast": cast}
        MOVIE_CREDITS_CACHE.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"Movie credits: {min(number * 45, len(missing))}/{len(missing)}", flush=True)
        time.sleep(0.05)
    return result


def load_people(qids: list[str]) -> dict[str, dict[str, str]]:
    cache = json.loads(PEOPLE_CACHE.read_text(encoding="utf-8")) if PEOPLE_CACHE.exists() else {}
    missing = [qid for qid in qids if qid not in cache]
    for number, batch in enumerate(chunks(missing, 45), 1):
        payload = api({
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "labels", "languages": "zh|zh-hans|en", "languagefallback": "0",
        }, endpoint=WIKIDATA_API)
        for qid, entity in payload.get("entities", {}).items():
            labels = entity.get("labels", {})
            en = labels.get("en", {}).get("value", "")
            cn = labels.get("zh-hans", {}).get("value", "") or labels.get("zh", {}).get("value", "") or en
            cache[qid] = {"cn": cn, "en": en or cn}
        PEOPLE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"People labels: {min(number * 45, len(missing))}/{len(missing)}", flush=True)
        time.sleep(0.05)
    return cache


def useful_english_summary(movie: dict) -> str:
    current = re.sub(r"\s+", " ", movie.get("summary_en") or movie.get("summary") or "").strip()
    if current and "百科资料条目" not in current and not current.startswith("暂无"):
        return current
    year = f" released in {movie['year']}" if movie.get("year") else ""
    return f"{movie['title_en']} is a film{year} associated with {movie['studio']} in the Disney catalog."


def translate_summaries(movies: list[dict]) -> dict[str, str]:
    cache = json.loads(SUMMARY_CACHE.read_text(encoding="utf-8")) if SUMMARY_CACHE.exists() else {}
    pending = [movie for movie in movies if movie["summary_key"] not in cache]
    groups: list[list[dict]] = []
    group: list[dict] = []
    length = 0
    for movie in pending:
        size = len(movie["summary_en"])
        if group and (len(group) >= 8 or length + size > 3200):
            groups.append(group); group = []; length = 0
        group.append(movie); length += size
    if group:
        groups.append(group)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(google_translate, [movie["summary_en"] for movie in batch]): batch for batch in groups}
        for number, future in enumerate(as_completed(futures), 1):
            batch = futures[future]
            translated = future.result()
            for movie, value in zip(batch, translated):
                cache[movie["summary_key"]] = value
            SUMMARY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            print(f"Chinese summaries: {number}/{len(groups)}", flush=True)
    return cache


def main() -> None:
    movies = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    resolve_missing_wikidata(movies)
    qids = sorted({movie.get("wikidata_id") for movie in movies if movie.get("wikidata_id")})
    credits = load_movie_credits(qids)
    people_ids = set()
    for credit in credits.values():
        people_ids.update(credit.get("directors", [])); people_ids.update(credit.get("cast", []))
    people = load_people(sorted(people_ids))

    for movie in movies:
        movie_credits = credits.get(movie.get("wikidata_id"), {})
        directors = [people.get(qid, {}) for qid in movie_credits.get("directors", [])]
        cast = [people.get(qid, {}) for qid in movie_credits.get("cast", [])]
        movie["director_cn"] = "、".join(x.get("cn", "") for x in directors if x.get("cn")) or movie.get("director", "资料暂缺")
        movie["director_en"] = ", ".join(x.get("en", "") for x in directors if x.get("en")) or movie.get("director", "Not available")
        movie["cast_cn"] = "、".join(x.get("cn", "") for x in cast if x.get("cn")) or "资料暂缺"
        movie["cast_en"] = ", ".join(x.get("en", "") for x in cast if x.get("en")) or "Not available"
        movie["director"] = movie["director_cn"]
        movie["cast"] = movie["cast_cn"]
        movie["summary_en"] = useful_english_summary(movie)
        movie["summary_key"] = movie.get("wikidata_id") or f"{movie['title_en']}:{movie.get('year', 0)}"

    summaries = translate_summaries(movies)
    for movie in movies:
        movie["summary_cn"] = summaries.get(movie["summary_key"], "暂无中文简介。")
        movie["summary"] = movie["summary_cn"]
        movie["summary_cn_source"] = "machine_translation"
        movie.pop("summary_key", None)
    write_catalog(movies)
    print(f"Enriched {len(movies)} films", flush=True)


if __name__ == "__main__":
    main()
