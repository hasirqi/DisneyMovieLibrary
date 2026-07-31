#!/usr/bin/env python3
"""Fill Chinese film titles from Wikidata, then a transparent MT fallback."""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

from sync_wikimedia import JSON_PATH, WIKIDATA_API, api, chunks, write_catalog

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "chinese_titles.json"
SEPARATOR = " ||| "
MANUAL_OVERRIDES = {
    "Lilo & Scratch": "莉萝与史迪奇",
    "Xuxa Gêmeas": "舒莎双胞胎",
    "Ek Hasina Thi (film)": "有位佳人",
    "Hot Water (1937 film)": "热水",
    "Midnight Taxi (1937 film)": "午夜出租车",
    "Off to the Races (film)": "奔赴赛场",
    "Thank You, Mr. Moto (film)": "谢谢你，莫托先生",
    "The Holy Terror (1937 film)": "神圣恐怖",
    "The Jones Family in Big Business": "琼斯一家经商记",
}


def clean_english_title(title: str) -> str:
    return re.sub(
        r"\s*\((?:upcoming\s+)?(?:\d{4}\s+)?(?:TV\s+|television\s+)?(?:film|short film)\)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def zh_labels(qids: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for number, batch in enumerate(chunks(qids, 45), 1):
        payload = api({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "labels",
            "languages": "zh|zh-hans|zh-cn",
            "languagefallback": "0",
        }, endpoint=WIKIDATA_API)
        for qid, entity in payload.get("entities", {}).items():
            available = entity.get("labels", {})
            value = next((available.get(code, {}).get("value", "") for code in ("zh-cn", "zh-hans", "zh") if available.get(code)), "")
            if value:
                labels[qid] = value
        print(f"Wikidata labels: batch {number}", flush=True)
        time.sleep(0.05)
    return labels


def google_translate(texts: list[str]) -> list[str]:
    query = SEPARATOR.join(texts)
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
        "client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": query,
    })
    raw = subprocess.check_output(["curl", "-fsSL", "--retry", "3", "-A", "DisneyMovieLibrary/2.1", url], text=True)
    payload = json.loads(raw)
    translated = "".join(piece[0] for piece in payload[0] if piece and piece[0])
    parts = [part.strip() for part in re.split(r"\s*\|\|\|\s*", translated)]
    if len(parts) != len(texts):
        if len(texts) == 1:
            return [translated.strip()]
        result: list[str] = []
        for text in texts:
            result.extend(google_translate([text]))
        return result
    return parts


def main() -> None:
    movies = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    missing = [movie for movie in movies if not has_chinese(movie.get("title_cn", ""))]
    qids = sorted({movie.get("wikidata_id") for movie in missing if movie.get("wikidata_id")})
    labels = zh_labels(qids)

    wiki_count = 0
    for movie in missing:
        value = labels.get(movie.get("wikidata_id", ""), "").strip()
        if value and value.casefold() != movie["title_en"].casefold():
            movie["title_cn"] = value
            movie["title_cn_source"] = "wikidata"
            wiki_count += 1

    remaining = [movie for movie in movies if not has_chinese(movie.get("title_cn", ""))]
    for index in range(0, len(remaining), 12):
        batch = remaining[index:index + 12]
        needs_api = [movie for movie in batch if movie["title_en"] not in cache]
        if needs_api:
            source_titles = [clean_english_title(movie["title_en"]) for movie in needs_api]
            translated = google_translate(source_titles)
            for movie, value in zip(needs_api, translated):
                cache[movie["title_en"]] = value or f"《{movie['title_en']}》"
        for movie in batch:
            movie["title_cn"] = cache[movie["title_en"]]
            movie["title_cn_source"] = "machine_translation"
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"Machine titles: {min(index + len(batch), len(remaining))}/{len(remaining)}", flush=True)
        time.sleep(0.12)

    for movie in movies:
        if movie["title_en"] in MANUAL_OVERRIDES:
            movie["title_cn"] = MANUAL_OVERRIDES[movie["title_en"]]
            movie["title_cn_source"] = "manual_override"

    write_catalog(movies)
    print(f"Updated {wiki_count} Wikidata titles and {len(remaining)} machine-assisted titles", flush=True)


if __name__ == "__main__":
    main()
