import os
import time
from urllib.parse import quote

import requests
from fastapi import FastAPI, Query
from pydantic import BaseModel

from services._shared.config import MUSICBRAINZ_APP_NAME, MUSICBRAINZ_CONTACT_EMAIL
from services._shared.db import execute, fetch_all, fetch_one
from services._shared.http import add_cors
from services._shared.logging_utils import configure_logging

logger = configure_logging("artist-service")
app = FastAPI(title="SceneRadar Artist Service", version="1.0.0")
add_cors(app)


class ArtistResolveRequest(BaseModel):
    name: str


@app.get("/artists/health")
def health():
    return {"status": "ok", "service": "artist-service"}


@app.get("/artists")
def artists(q: str | None = Query(None)):
    if q:
        return fetch_all(
            """
            SELECT id, mbid, name, sort_name, country, artist_type, disambiguation, popularity::float
            FROM artists
            WHERE LOWER(name) LIKE LOWER(%s)
            ORDER BY popularity DESC NULLS LAST, name
            """,
            (f"%{q}%",),
        )
    return fetch_all(
        """
        SELECT id, mbid, name, sort_name, country, artist_type, disambiguation, popularity::float
        FROM artists
        ORDER BY popularity DESC NULLS LAST, name
        """
    )


@app.get("/artists/{artist_id}")
def artist(artist_id: int):
    return fetch_one(
        """
        SELECT id, mbid, name, sort_name, country, artist_type, disambiguation, popularity::float
        FROM artists WHERE id = %s
        """,
        (artist_id,),
    )


def user_agent() -> str:
    contact = MUSICBRAINZ_CONTACT_EMAIL or os.getenv("MUSICBRAINZ_CONTACT_EMAIL", "")
    app_name = MUSICBRAINZ_APP_NAME or "SceneRadarStudentProject"
    if contact:
        return f"{app_name}/1.0 ({contact})"
    return f"{app_name}/1.0"


def search_musicbrainz_artist(name: str) -> dict | None:
    response = requests.get(
        "https://musicbrainz.org/ws/2/artist/",
        params={"query": f'artist:"{name}"', "fmt": "json", "limit": 1},
        headers={"User-Agent": user_agent(), "Accept": "application/json"},
        timeout=25,
    )
    response.raise_for_status()
    artists = response.json().get("artists", [])
    return artists[0] if artists else None


@app.post("/artists/resolve")
def resolve_artist(payload: ArtistResolveRequest):
    normalized = " ".join(payload.name.strip().split())
    existing = fetch_one("SELECT id FROM artists WHERE LOWER(name) = LOWER(%s)", (normalized,))
    if not existing:
        execute(
            "INSERT INTO artists (name, sort_name, artist_type) VALUES (%s, %s, 'unknown') ON CONFLICT (name) DO NOTHING",
            (normalized, normalized),
        )

    try:
        mb_artist = search_musicbrainz_artist(normalized)
        if mb_artist:
            execute(
                """
                UPDATE artists
                SET mbid = %s,
                    name = COALESCE(%s, name),
                    sort_name = %s,
                    country = %s,
                    artist_type = %s,
                    disambiguation = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE LOWER(name) = LOWER(%s)
                """,
                (
                    mb_artist.get("id"),
                    mb_artist.get("name"),
                    mb_artist.get("sort-name") or mb_artist.get("name"),
                    mb_artist.get("country"),
                    mb_artist.get("type") or "unknown",
                    mb_artist.get("disambiguation"),
                    normalized,
                ),
            )
    except Exception as exc:
        logger.warning("MusicBrainz resolution failed for %s: %s", normalized, exc)

    logger.info("Resolved artist through MusicBrainz lookup: %s", normalized)
    return fetch_one(
        "SELECT id, mbid, name, sort_name, country, artist_type, disambiguation, popularity::float FROM artists WHERE LOWER(name) = LOWER(%s)",
        (normalized,),
    )


@app.post("/artists/refresh")
def refresh_artists(limit: int = Query(100, ge=1, le=500)):
    """Resolve artists imported from Ticketmaster against MusicBrainz.

    MusicBrainz does not require an API key, but it expects a meaningful
    User-Agent. Set MUSICBRAINZ_CONTACT_EMAIL in .env.
    """
    started = time.time()
    rows = fetch_all(
        """
        SELECT id, name
        FROM artists
        WHERE mbid IS NULL OR mbid = ''
        ORDER BY id
        LIMIT %s
        """,
        (limit,),
    )

    resolved = 0
    errors = 0

    for row in rows:
        try:
            mb_artist = search_musicbrainz_artist(row["name"])
            if mb_artist:
                execute(
                    """
                    UPDATE artists
                    SET mbid = %s,
                        sort_name = %s,
                        country = %s,
                        artist_type = %s,
                        disambiguation = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        mb_artist.get("id"),
                        mb_artist.get("sort-name") or mb_artist.get("name"),
                        mb_artist.get("country"),
                        mb_artist.get("type") or "unknown",
                        mb_artist.get("disambiguation"),
                        row["id"],
                    ),
                )
                resolved += 1
            time.sleep(1.1)
        except Exception as exc:
            logger.warning("MusicBrainz lookup failed for %s: %s", row["name"], exc)
            errors += 1

    duration_ms = int((time.time() - started) * 1000)
    execute(
        """
        INSERT INTO ingestion_logs (service_name, source_name, status, records_fetched, records_saved, error_message, started_at, finished_at, duration_ms)
        VALUES ('artist-service', 'MusicBrainz', %s, %s, %s, %s, NOW() - (%s || ' milliseconds')::interval, NOW(), %s)
        """,
        ("success" if errors == 0 else "partial", len(rows), resolved, None if errors == 0 else f"errors={errors}", duration_ms, duration_ms),
    )
    return {"status": "ok" if errors == 0 else "partial", "source": "MusicBrainz", "checked": len(rows), "resolved": resolved, "errors": errors}
