import asyncio
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query

from services._shared.http import add_cors
from services._shared.db import fetch_all
from services._shared.logging_utils import configure_logging

logger = configure_logging("api-gateway")
app = FastAPI(title="SceneRadar API Gateway", version="1.0.0")
add_cors(app)

CITY_SERVICE_URL = os.getenv("CITY_SERVICE_URL", "http://city-service:8001")
EVENTS_SERVICE_URL = os.getenv("EVENTS_SERVICE_URL", "http://events-service:8002")
ARTIST_SERVICE_URL = os.getenv("ARTIST_SERVICE_URL", "http://artist-service:8003")
GENRE_SERVICE_URL = os.getenv("GENRE_SERVICE_URL", "http://genre-service:8004")
VENUE_SERVICE_URL = os.getenv("VENUE_SERVICE_URL", "http://venue-service:8005")
SCORING_SERVICE_URL = os.getenv("SCORING_SERVICE_URL", "http://scoring-service:8006")


async def request_json(method: str, url: str, timeout: float = 45.0, **kwargs: Any) -> Any:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        logger.exception("Service returned an HTTP error")
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        logger.exception("Internal service unavailable")
        raise HTTPException(status_code=503, detail=f"Internal service unavailable: {exc}")


async def safe_request_json(name: str, method: str, url: str, timeout: float = 180.0, **kwargs: Any) -> dict[str, Any]:
    try:
        result = await request_json(method, url, timeout=timeout, **kwargs)
        if isinstance(result, dict):
            return result
        return {"status": "ok", "data": result}
    except HTTPException as exc:
        return {"status": "error", "service": name, "detail": exc.detail}


@app.get("/api/health")
async def health():
    services = {
        "city": CITY_SERVICE_URL,
        "events": EVENTS_SERVICE_URL,
        "artist": ARTIST_SERVICE_URL,
        "genre": GENRE_SERVICE_URL,
        "venue": VENUE_SERVICE_URL,
        "scoring": SCORING_SERVICE_URL,
    }
    return {"status": "ok", "service": "api-gateway", "services": services}


@app.get("/api/cities")
async def cities():
    return await request_json("GET", f"{CITY_SERVICE_URL}/cities")


@app.get("/api/genres")
async def genres():
    return await request_json("GET", f"{GENRE_SERVICE_URL}/genres")


@app.get("/api/ranking")
async def ranking(
    genre: str = Query("metal"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    params = {"genre": genre}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    return await request_json("GET", f"{SCORING_SERVICE_URL}/score/ranking", params=params)


@app.get("/api/cities/{city_id}")
async def city_details(city_id: int):
    return await request_json("GET", f"{CITY_SERVICE_URL}/cities/{city_id}")


@app.get("/api/cities/{city_id}/events")
async def city_events(
    city_id: int,
    genre: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
):
    params = {"city_id": city_id, "limit": limit, "upcoming_only": True}
    if genre and genre.lower() != "all":
        params["genre"] = genre
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    return await request_json("GET", f"{EVENTS_SERVICE_URL}/events", params=params)


@app.get("/api/cities/{city_id}/venues")
async def city_venues(city_id: int):
    return await request_json("GET", f"{VENUE_SERVICE_URL}/venues", params={"city_id": city_id})


@app.get("/api/cities/{city_id}/score")
async def city_score(city_id: int, genre: str = Query("metal")):
    return await request_json("GET", f"{SCORING_SERVICE_URL}/score", params={"city_id": city_id, "genre": genre})


@app.get("/api/dashboard/{city_id}")
async def dashboard(
    city_id: int,
    genre: str = Query("metal"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    events_limit: int = Query(50, ge=1, le=200),
):
    city = await city_details(city_id)
    score = await city_score(city_id, genre)

    all_events = await city_events(city_id, None, date_from=date_from, date_to=date_to, limit=200)
    events = all_events if genre.lower() == "all" else await city_events(city_id, genre, date_from=date_from, date_to=date_to, limit=events_limit)
    venues = await city_venues(city_id)

    diagnostics = {
        "events_total_for_city": len(all_events),
        "events_visible_after_filter": len(events),
        "venues_total_for_city": len(venues),
        "active_genre": genre,
    }

    return {"city": city, "score": score, "events": events, "venues": venues, "diagnostics": diagnostics}


@app.post("/api/refresh")
async def refresh_data(
    include_overpass: bool = Query(False, description="Run slow Overpass venue refresh. Default false because Overpass often rate-limits."),
    include_musicbrainz: bool = Query(False, description="Run slow MusicBrainz artist enrichment. Default false for faster refresh."),
):
    logger.info("Starting parallel refresh across ingestion services")

    # Stage 1: independent source ingestion. Ticketmaster is essential; Overpass
    # is optional and slow, because Ticketmaster already stores event venues.
    events_task = asyncio.create_task(
        safe_request_json(
            "events-service",
            "POST",
            f"{EVENTS_SERVICE_URL}/events/refresh",
            timeout=420.0,
            params={"max_workers": 2, "page_size": 100, "max_pages": 10, "days_ahead": 365, "radius_km": 50, "use_geo": True},
        )
    )

    venues_task = None
    if include_overpass:
        venues_task = asyncio.create_task(
            safe_request_json("venue-service", "POST", f"{VENUE_SERVICE_URL}/venues/refresh", timeout=300.0)
        )

    events = await events_task

    # Stage 2: enrich artists/tags after events have inserted artist rows.
    enrichment_tasks = {
        "genres": asyncio.create_task(
            safe_request_json(
                "genre-service",
                "POST",
                f"{GENRE_SERVICE_URL}/genres/refresh",
                timeout=180.0,
                params={"max_workers": 2, "page_size": 100, "max_pages": 10, "days_ahead": 365, "radius_km": 50, "use_geo": True},
            )
        )
    }

    if include_musicbrainz:
        enrichment_tasks["artists"] = asyncio.create_task(
            safe_request_json("artist-service", "POST", f"{ARTIST_SERVICE_URL}/artists/refresh", timeout=300.0)
        )

    if venues_task is not None:
        enrichment_tasks["venues"] = venues_task
    else:
        enrichment_tasks["venues"] = asyncio.create_task(asyncio.sleep(0, result={
            "status": "skipped",
            "source": "OpenStreetMap/Overpass",
            "message": "Skipped in fast refresh. Use POST /api/refresh/venues or /api/refresh?include_overpass=true.",
        }))

    if "artists" not in enrichment_tasks:
        enrichment_tasks["artists"] = asyncio.create_task(asyncio.sleep(0, result={
            "status": "skipped",
            "source": "MusicBrainz",
            "message": "Skipped in fast refresh. Use POST /api/refresh/artists or /api/refresh?include_musicbrainz=true.",
        }))

    gathered = await asyncio.gather(*enrichment_tasks.values())
    enrichment = dict(zip(enrichment_tasks.keys(), gathered))

    # Stage 3: scoring must run after the refresh/enrichment stage.
    scores = await safe_request_json("scoring-service", "POST", f"{SCORING_SERVICE_URL}/score/recalculate", timeout=120.0)

    results = {
        "events": events,
        "artists": enrichment["artists"],
        "genres": enrichment["genres"],
        "venues": enrichment["venues"],
        "scores": scores,
    }

    statuses = [value.get("status") for value in results.values()]
    overall_status = "ok" if all(status in {"ok", "success", "skipped"} for status in statuses) else "partial"

    return {
        "status": overall_status,
        "mode": "parallel-fast",
        "message": "Parallel refresh finished. Slow sources are optional; check per-service results below.",
        **results,
    }


@app.post("/api/refresh/events")
async def refresh_events_only(
    max_workers: int = Query(2, ge=1, le=4),
    page_size: int = Query(100, ge=20, le=100),
    max_pages: int = Query(10, ge=1, le=10),
    days_ahead: int = Query(365, ge=30, le=730),
    radius_km: int = Query(50, ge=5, le=100),
    use_geo: bool = Query(True),
):
    return await safe_request_json(
        "events-service",
        "POST",
        f"{EVENTS_SERVICE_URL}/events/refresh",
        timeout=420.0,
        params={
            "max_workers": max_workers,
            "page_size": page_size,
            "max_pages": max_pages,
            "days_ahead": days_ahead,
            "radius_km": radius_km,
            "use_geo": use_geo,
        },
    )


@app.post("/api/refresh/venues")
async def refresh_venues_only():
    return await safe_request_json("venue-service", "POST", f"{VENUE_SERVICE_URL}/venues/refresh", timeout=240.0)


@app.post("/api/refresh/genres")
async def refresh_genres_only():
    return await safe_request_json("genre-service", "POST", f"{GENRE_SERVICE_URL}/genres/refresh", timeout=240.0)


@app.post("/api/refresh/artists")
async def refresh_artists_only():
    return await safe_request_json("artist-service", "POST", f"{ARTIST_SERVICE_URL}/artists/refresh", timeout=240.0)


@app.post("/api/refresh/scores")
async def refresh_scores_only():
    return await safe_request_json("scoring-service", "POST", f"{SCORING_SERVICE_URL}/score/recalculate", timeout=120.0)


@app.get("/api/ingestion-logs")
async def ingestion_logs(limit: int = Query(30, ge=1, le=200)):
    return fetch_all(
        """
        SELECT service_name, source_name, status, records_fetched, records_saved,
               error_message, started_at::text, finished_at::text, duration_ms
        FROM ingestion_logs
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )
