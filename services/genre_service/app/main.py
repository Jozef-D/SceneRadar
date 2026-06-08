import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from services._shared.config import LASTFM_API_KEY
from services._shared.db import execute, fetch_all
from services._shared.genres import PUBLIC_GENRES, SUPPORTED_GENRES, map_tag_to_genre
from services._shared.http import add_cors
from services._shared.logging_utils import configure_logging

logger = configure_logging("genre-service")
app = FastAPI(title="SceneRadar Genre Service", version="1.0.0")
add_cors(app)


class TagRequest(BaseModel):
    artist_id: int
    tag_name: str
    tag_weight: float = 50


@app.get("/genres/health")
def health():
    return {"status": "ok", "service": "genre-service"}


@app.get("/genres")
def genres():
    return PUBLIC_GENRES


@app.post("/genres/classify-artist")
def classify_artist(payload: TagRequest):
    main_genre = map_tag_to_genre(payload.tag_name)
    if not main_genre:
        raise HTTPException(status_code=400, detail="Unsupported tag")
    execute(
        """
        INSERT INTO artist_tags (artist_id, tag_name, tag_weight, main_genre, source)
        VALUES (%s, %s, %s, %s, 'manual')
        ON CONFLICT (artist_id, tag_name, source) DO UPDATE SET
            tag_weight = EXCLUDED.tag_weight,
            main_genre = EXCLUDED.main_genre
        """,
        (payload.artist_id, payload.tag_name, payload.tag_weight, main_genre),
    )
    return {"artist_id": payload.artist_id, "tag": payload.tag_name, "main_genre": main_genre}


@app.get("/genres/artists")
def artist_genres():
    return fetch_all(
        """
        SELECT a.id AS artist_id, a.name AS artist_name, at.tag_name, at.tag_weight::float, at.main_genre, at.source
        FROM artists a
        JOIN artist_tags at ON at.artist_id = a.id
        ORDER BY at.main_genre, at.tag_weight DESC
        """
    )


def lastfm_get(params: dict[str, Any]) -> dict[str, Any]:
    api_key = (LASTFM_API_KEY or os.getenv("LASTFM_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("LASTFM_API_KEY is missing")

    response = requests.get(
        "https://ws.audioscrobbler.com/2.0/",
        params={**params, "api_key": api_key, "format": "json"},
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Last.fm error {data.get('error')}: {data.get('message')}")
    return data


def normalize_popularity(listeners: str | int | None, playcount: str | int | None) -> float | None:
    # Last.fm values can differ by many orders of magnitude. A log scale is
    # enough for a relative 0-100 project score.
    try:
        listeners_value = max(float(listeners or 0), 0)
        playcount_value = max(float(playcount or 0), 0)
    except (TypeError, ValueError):
        return None
    signal = listeners_value + 0.15 * playcount_value
    if signal <= 0:
        return None
    score = min(100.0, max(5.0, 20.0 * math.log10(signal + 1.0)))
    return round(score, 2)


def refresh_one_artist(row: dict[str, Any]) -> tuple[int, int]:
    artist_id = row["id"]
    artist_name = row["name"]
    mbid = row.get("mbid")

    saved_tags = 0
    updated_popularity = 0

    info_params = {"method": "artist.getinfo", "artist": artist_name, "autocorrect": 1}
    if mbid:
        info_params["mbid"] = mbid
    try:
        info = lastfm_get(info_params).get("artist", {})
        stats = info.get("stats", {})
        popularity = normalize_popularity(stats.get("listeners"), stats.get("playcount"))
        if popularity is not None:
            execute("UPDATE artists SET popularity = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (popularity, artist_id))
            updated_popularity = 1
    except Exception as exc:
        logger.warning("Last.fm artist.getInfo failed for %s: %s", artist_name, exc)

    tag_params = {"method": "artist.gettoptags", "artist": artist_name, "autocorrect": 1}
    if mbid:
        tag_params["mbid"] = mbid
    data = lastfm_get(tag_params)
    tags = data.get("toptags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]

    for tag in tags[:15]:
        tag_name = str(tag.get("name", "")).strip().lower()
        if not tag_name:
            continue
        mapped = map_tag_to_genre(tag_name)
        if not mapped:
            continue
        try:
            weight = float(tag.get("count") or 50)
        except (TypeError, ValueError):
            weight = 50
        execute(
            """
            INSERT INTO artist_tags (artist_id, tag_name, tag_weight, main_genre, source)
            VALUES (%s, %s, %s, %s, 'Last.fm')
            ON CONFLICT (artist_id, tag_name, source) DO UPDATE SET
                tag_weight = EXCLUDED.tag_weight,
                main_genre = EXCLUDED.main_genre
            """,
            (artist_id, tag_name, weight, mapped),
        )
        saved_tags += 1

    return saved_tags, updated_popularity


@app.post("/genres/refresh")
def refresh_genres(
    limit: int = Query(100, ge=1, le=500),
    max_workers: int = Query(4, ge=1, le=8),
):
    """Fetch real artist tags and popularity from Last.fm.

    Artists are processed in parallel with a bounded worker pool. Last.fm is less
    restrictive than MusicBrainz, but the default is still conservative.
    """
    started = time.time()
    api_key = (LASTFM_API_KEY or os.getenv("LASTFM_API_KEY", "")).strip()
    if not api_key:
        duration_ms = int((time.time() - started) * 1000)
        execute(
            """
            INSERT INTO ingestion_logs (service_name, source_name, status, records_fetched, records_saved, error_message, started_at, finished_at, duration_ms)
            VALUES ('genre-service', 'Last.fm', 'skipped', 0, 0, 'Missing LASTFM_API_KEY', NOW() - (%s || ' milliseconds')::interval, NOW(), %s)
            """,
            (duration_ms, duration_ms),
        )
        return {"status": "skipped", "source": "Last.fm", "message": "LASTFM_API_KEY is missing", "artists_checked": 0, "tags_saved": 0}

    artists = fetch_all(
        """
        SELECT DISTINCT a.id, a.name, a.mbid
        FROM artists a
        JOIN events e ON e.artist_id = a.id
        WHERE e.event_date >= CURRENT_DATE
        ORDER BY a.id
        LIMIT %s
        """,
        (limit,),
    )

    checked = 0
    tags_saved = 0
    popularity_updated = 0
    errors = 0

    if artists:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(artists))) as executor:
            futures = {executor.submit(refresh_one_artist, row): row for row in artists}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    saved_tags, updated_popularity = future.result()
                    tags_saved += saved_tags
                    popularity_updated += updated_popularity
                    checked += 1
                except Exception as exc:
                    logger.warning("Last.fm refresh failed for %s: %s", row["name"], exc)
                    errors += 1

    duration_ms = int((time.time() - started) * 1000)
    execute(
        """
        INSERT INTO ingestion_logs (service_name, source_name, status, records_fetched, records_saved, error_message, started_at, finished_at, duration_ms)
        VALUES ('genre-service', 'Last.fm', %s, %s, %s, %s, NOW() - (%s || ' milliseconds')::interval, NOW(), %s)
        """,
        ("success" if errors == 0 else "partial", len(artists), tags_saved, None if errors == 0 else f"errors={errors}", duration_ms, duration_ms),
    )

    return {
        "status": "ok" if errors == 0 else "partial",
        "source": "Last.fm",
        "mode": "parallel",
        "max_workers": max_workers,
        "artists_checked": checked,
        "tags_saved": tags_saved,
        "popularity_updated": popularity_updated,
        "errors": errors,
    }
