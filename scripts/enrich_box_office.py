#!/usr/bin/env python3
"""Add clearly scoped theatrical box-office grosses from Wikidata P2142.

Worldwide totals are preferred. If unavailable, a United States total may be
used and is explicitly labelled. Unqualified amounts and non-USD values are
ignored so the UI never mixes currencies or geographic scopes.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "movies.json"
JS_PATH = ROOT / "data" / "movies.js"
API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "DisneyMovieLibrary/2.0 (https://github.com/hasirqi/DisneyMovieLibrary)"
USD = "Q4917"
WORLDWIDE = "Q13780930"
UNITED_STATES = "Q30"


def chunks(values: list[str], size: int = 45) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def fetch_entities(qids: list[str]) -> dict[str, Any]:
    entities: dict[str, Any] = {}
    for number, batch in enumerate(chunks(qids), 1):
        query = urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "claims",
            "format": "json",
        })
        payload = json.loads(subprocess.check_output([
            "curl", "-fsSL", "--retry", "3", "-A", USER_AGENT, f"{API}?{query}"
        ], text=True))
        entities.update(payload.get("entities", {}))
        if number % 10 == 0:
            print(f"Wikidata batches: {number}", flush=True)
        time.sleep(0.08)
    return entities


def item_ids(snaks: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for snak in snaks:
        value = snak.get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            found.add(value["id"])
    return found


def choose_gross(entity: dict[str, Any]) -> tuple[int, str] | None:
    candidates: list[tuple[int, int, str]] = []
    for statement in entity.get("claims", {}).get("P2142", []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if not isinstance(value, dict):
            continue
        unit = str(value.get("unit", "")).rsplit("/", 1)[-1]
        if unit != USD:
            continue
        try:
            amount = int(float(value.get("amount", 0)))
        except (TypeError, ValueError):
            continue
        territories = item_ids(statement.get("qualifiers", {}).get("P3005", []))
        if WORLDWIDE in territories:
            candidates.append((2, amount, "worldwide"))
        elif UNITED_STATES in territories:
            candidates.append((1, amount, "united_states"))
    if not candidates:
        return None
    _, amount, scope = max(candidates, key=lambda item: (item[0], item[1]))
    return amount, scope


def write_catalog(movies: list[dict[str, Any]]) -> None:
    payload = json.dumps(movies, ensure_ascii=False, separators=(",", ":"))
    JSON_PATH.write_text(payload + "\n", encoding="utf-8")
    JS_PATH.write_text("window.__LOCAL_MOVIES__=" + payload + ";\n", encoding="utf-8")


def main() -> None:
    movies: list[dict[str, Any]] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    qids = sorted({movie["wikidata_id"] for movie in movies if movie.get("wikidata_id")})
    entities = fetch_entities(qids)
    updated = 0
    for movie in movies:
        gross = choose_gross(entities.get(movie.get("wikidata_id", ""), {}))
        for field in ("box_office_amount", "box_office_currency", "box_office_scope", "box_office_source"):
            movie.pop(field, None)
        if not gross:
            continue
        amount, scope = gross
        movie.update({
            "box_office_amount": amount,
            "box_office_currency": "USD",
            "box_office_scope": scope,
            "box_office_source": "Wikidata P2142",
        })
        updated += 1
    write_catalog(movies)
    print(f"Added clearly scoped box office to {updated}/{len(movies)} films")


if __name__ == "__main__":
    main()
