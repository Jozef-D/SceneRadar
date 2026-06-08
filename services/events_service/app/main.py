import datetime as dt
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from fastapi import FastAPI, Query

from services._shared.config import TICKETMASTER_API_KEY
from services._shared.db import execute, fetch_all, fetch_one
from services._shared.genres import SUPPORTED_GENRES, map_tag_to_genre, normalize_tag
from services._shared.http import add_cors
from services._shared.logging_utils import configure_logging

logger = configure_logging("events-service")
app = FastAPI(title="SceneRadar Events Service", version="1.0.0")
add_cors(app)


@app.get("/events/health")
def health():
    return {"status": "ok", "service": "events-service"}


def log_ingestion(status: str, fetched: int, saved: int, error: str | None, started: float):
    duration_ms = int((time.time() - started) * 1000)
    execute(
        """
        INSERT INTO ingestion_logs
        (service_name, source_name, status, records_fetched, records_saved, error_message, started_at, finished_at, duration_ms)
        VALUES ('events-service', 'Ticketmaster', %s, %s, %s, %s, NOW() - (%s || ' milliseconds')::interval, NOW(), %s)
        """,
        (status, fetched, saved, error, duration_ms, duration_ms),
    )


@app.post("/events/refresh")
def refresh_events(
    max_workers: int = Query(2, ge=1, le=4),
    page_size: int = Query(100, ge=20, le=100),
    max_pages: int = Query(10, ge=1, le=10),
    days_ahead: int = Query(365, ge=30, le=730),
    radius_km: int = Query(50, ge=5, le=100),
    use_geo: bool = Query(True),
):
    """Fetch real upcoming music events from Ticketmaster Discovery API.

    Improvements over the first version:
    - fetches multiple pages per city instead of only the first page,
    - uses a geohash/radius search by default, so events near the city are not
      missed when Ticketmaster stores a venue in a neighbouring town,
    - returns page diagnostics per city.

    Ticketmaster supports pagination with `size` and `page`, and deep paging is
    limited, so this endpoint caps the request to max 10 pages of 100 results.
    """
    started = time.time()
    api_key = (TICKETMASTER_API_KEY or os.getenv("TICKETMASTER_API_KEY", "")).strip()

    if not api_key:
        log_ingestion("skipped", 0, 0, "Missing TICKETMASTER_API_KEY", started)
        return {
            "status": "skipped",
            "source": "Ticketmaster",
            "message": "TICKETMASTER_API_KEY is missing. No events were imported.",
            "records_fetched": 0,
            "records_saved": 0,
        }

    try:
        cities = fetch_all("SELECT id, name, latitude::float, longitude::float FROM cities ORDER BY id")

        start_dt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        end_dt = start_dt + dt.timedelta(days=days_ahead)
        start_iso = start_dt.isoformat().replace("+00:00", "Z")
        end_iso = end_dt.isoformat().replace("+00:00", "Z")

        execute("DELETE FROM events WHERE source = 'Ticketmaster' AND event_date < CURRENT_DATE")

        def fetch_city(city: dict[str, Any]) -> dict[str, Any]:
            logger.info("Fetching Ticketmaster events for city=%s", city["name"])
            city_saved = 0
            city_fetched = 0
            pages_fetched = 0
            reported_total = None

            for page in range(max_pages):
                params = {
                    "apikey": api_key,
                    "countryCode": "PL",
                    "classificationName": "music",
                    "size": page_size,
                    "page": page,
                    "startDateTime": start_iso,
                    "endDateTime": end_iso,
                    "sort": "date,asc",
                    "locale": "*",
                }

                if use_geo:
                    params.update({
                        "geoPoint": geohash_encode(float(city["latitude"]), float(city["longitude"]), precision=8),
                        "radius": radius_km,
                        "unit": "km",
                    })
                else:
                    params["city"] = city["name"]

                response = requests.get(
                    "https://app.ticketmaster.com/discovery/v2/events.json",
                    params=params,
                    timeout=25,
                )
                response.raise_for_status()
                data = response.json()
                page_meta = data.get("page", {})
                reported_total = page_meta.get("totalElements", reported_total)
                total_pages = page_meta.get("totalPages")
                raw_events = data.get("_embedded", {}).get("events", [])

                if not raw_events:
                    break

                pages_fetched += 1
                city_fetched += len(raw_events)
                for raw in raw_events:
                    city_saved += upsert_ticketmaster_event(city["id"], raw)

                if total_pages is not None and page + 1 >= int(total_pages):
                    break

                # A small delay keeps the parallel ingestion friendlier to the API.
                time.sleep(0.25)

            return {
                "city": city["name"],
                "mode": "geo" if use_geo else "city",
                "radius_km": radius_km if use_geo else None,
                "pages_fetched": pages_fetched,
                "reported_total": reported_total,
                "fetched": city_fetched,
                "saved": city_saved,
            }

        errors: list[str] = []
        city_results: list[dict[str, Any]] = []
        fetched = 0
        saved = 0

        with ThreadPoolExecutor(max_workers=min(max_workers, len(cities) or 1)) as executor:
            futures = {executor.submit(fetch_city, city): city for city in cities}
            for future in as_completed(futures):
                city = futures[future]
                try:
                    result = future.result()
                    city_results.append(result)
                    fetched += int(result.get("fetched", 0))
                    saved += int(result.get("saved", 0))
                except Exception as city_exc:
                    message = f"{city['name']}: {city_exc}"
                    logger.warning("Ticketmaster city fetch failed: %s", message)
                    errors.append(message)
                    city_results.append({"city": city["name"], "status": "error", "message": str(city_exc)})

        city_results.sort(key=lambda item: item.get("city", ""))
        status = "success" if not errors else "partial"
        log_ingestion(status, fetched, saved, "; ".join(errors) if errors else None, started)
        return {
            "status": "ok" if not errors else "partial",
            "source": "Ticketmaster",
            "mode": "parallel-paginated-geo" if use_geo else "parallel-paginated-city",
            "max_workers": max_workers,
            "page_size": page_size,
            "max_pages": max_pages,
            "days_ahead": days_ahead,
            "radius_km": radius_km if use_geo else None,
            "records_fetched": fetched,
            "records_saved": saved,
            "errors": errors,
            "cities": city_results,
        }
    except Exception as exc:
        logger.exception("Ticketmaster ingestion failed")
        log_ingestion("error", 0, 0, str(exc), started)
        return {"status": "error", "source": "Ticketmaster", "message": str(exc), "records_fetched": 0, "records_saved": 0}


_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(latitude: float, longitude: float, precision: int = 8) -> str:
    """Small geohash encoder to avoid an extra dependency."""
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash = []
    bit = 0
    ch = 0
    even = True

    while len(geohash) < precision:
        if even:
            mid = sum(lon_interval) / 2
            if longitude >= mid:
                ch = (ch << 1) + 1
                lon_interval[0] = mid
            else:
                ch = (ch << 1)
                lon_interval[1] = mid
        else:
            mid = sum(lat_interval) / 2
            if latitude >= mid:
                ch = (ch << 1) + 1
                lat_interval[0] = mid
            else:
                ch = (ch << 1)
                lat_interval[1] = mid

        even = not even
        bit += 1
        if bit == 5:
            geohash.append(_BASE32[ch])
            bit = 0
            ch = 0

    return "".join(geohash)


def upsert_ticketmaster_event(city_id: int, raw: dict[str, Any]) -> int:
    external_id = raw.get("id")
    if not external_id:
        return 0

    name = raw.get("name", "Unknown event")
    url = raw.get("url")
    dates = raw.get("dates", {}).get("start", {})
    local_date = dates.get("localDate")
    if not local_date:
        return 0
    local_time = dates.get("localTime") or "20:00:00"

    classifications = raw.get("classifications", [{}]) or [{}]
    first_classification = classifications[0] if classifications else {}
    segment = nested_name(first_classification, "segment") or "music"
    genre = nested_name(first_classification, "genre")
    subgenre = nested_name(first_classification, "subGenre")

    embedded = raw.get("_embedded", {})
    attractions = embedded.get("attractions", [])
    artist_name = attractions[0].get("name") if attractions else extract_artist_from_event_name(name)
    venues = embedded.get("venues", [])
    venue = venues[0] if venues else {}

    venue_name = venue.get("name")
    lat = safe_float(venue.get("location", {}).get("latitude"))
    lon = safe_float(venue.get("location", {}).get("longitude"))
    address = build_venue_address(venue)
    assigned_city_id = resolve_event_city_id(city_id, venue, lat, lon)

    artist_id = ensure_artist(artist_name)
    main_genre, tag_name = infer_main_genre(genre, subgenre, name)

    if artist_id and main_genre:
        ensure_artist_tag(artist_id, tag_name or main_genre, main_genre, "Ticketmaster")

    venue_id = ensure_venue(assigned_city_id, venue_name, lat, lon, address, "Ticketmaster")

    execute(
        """
        INSERT INTO events
            (external_id, name, city_id, venue_id, artist_id, event_date, event_time,
             category, genre_raw, subgenre_raw, artist_name_raw, source, url, latitude, longitude)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Ticketmaster', %s, %s, %s)
        ON CONFLICT (external_id, source) DO UPDATE SET
            name = EXCLUDED.name,
            city_id = EXCLUDED.city_id,
            venue_id = EXCLUDED.venue_id,
            artist_id = EXCLUDED.artist_id,
            event_date = EXCLUDED.event_date,
            event_time = EXCLUDED.event_time,
            category = EXCLUDED.category,
            genre_raw = EXCLUDED.genre_raw,
            subgenre_raw = EXCLUDED.subgenre_raw,
            artist_name_raw = EXCLUDED.artist_name_raw,
            url = EXCLUDED.url,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            external_id, name, assigned_city_id, venue_id, artist_id, local_date, local_time,
            segment, main_genre or normalize_text(genre), normalize_text(subgenre), artist_name,
            url, lat, lon,
        ),
    )
    return 1


def nested_name(classification: dict[str, Any], key: str) -> str | None:
    value = classification.get(key)
    if isinstance(value, dict):
        return value.get("name")
    return None


def safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_text(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def build_venue_address(venue: dict[str, Any]) -> str | None:
    parts = []
    address = venue.get("address", {}).get("line1")
    city = venue.get("city", {}).get("name")
    country = venue.get("country", {}).get("name")
    for part in [address, city, country]:
        if part:
            parts.append(part)
    return ", ".join(parts) if parts else None


def extract_artist_from_event_name(name: str) -> str:
    for sep in [" - ", " — ", " / ", ","]:
        if sep in name:
            return name.split(sep)[0].strip()
    return name.strip()


def ensure_artist(artist_name: str | None) -> int | None:
    if not artist_name:
        return None

    normalized = " ".join(artist_name.strip().split())
    existing = fetch_one("SELECT id FROM artists WHERE LOWER(name) = LOWER(%s)", (normalized,))
    if existing:
        return existing["id"]

    execute(
        """
        INSERT INTO artists (mbid, name, sort_name, country, artist_type, popularity)
        VALUES (NULL, %s, %s, NULL, 'unknown', NULL)
        ON CONFLICT (name) DO NOTHING
        """,
        (normalized, normalized),
    )
    row = fetch_one("SELECT id FROM artists WHERE LOWER(name) = LOWER(%s)", (normalized,))
    return row["id"] if row else None


def infer_main_genre(genre: str | None, subgenre: str | None, event_name: str | None = None) -> tuple[str | None, str | None]:
    candidates = [subgenre, genre, event_name]
    for candidate in candidates:
        if not candidate:
            continue
        text = normalize_tag(candidate)

        mapped = map_tag_to_genre(text)
        if mapped:
            return mapped, text

        for supported in SUPPORTED_GENRES:
            if supported in text:
                return supported, text

    return None, normalize_text(subgenre) or normalize_text(genre)


def ensure_artist_tag(artist_id: int, tag_name: str, main_genre: str, source: str):
    execute(
        """
        INSERT INTO artist_tags (artist_id, tag_name, tag_weight, main_genre, source)
        VALUES (%s, %s, 50, %s, %s)
        ON CONFLICT (artist_id, tag_name, source) DO UPDATE SET
            main_genre = EXCLUDED.main_genRE,
            tag_weight = EXCLUDED.tag_weight
        """.replace("main_genRE", "main_genre"),
        (artist_id, tag_name, main_genre, source),
    )


def normalize_city_name(value: str | None) -> str:
    if not value:
        return ""
    replacements = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ż": "z", "ź": "z",
        "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n", "Ó": "o", "Ś": "s", "Ż": "z", "Ź": "z",
    }
    normalized = "".join(replacements.get(ch, ch) for ch in str(value))
    return " ".join(normalized.lower().split())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def resolve_event_city_id(query_city_id: int, venue: dict[str, Any], lat: float | None, lon: float | None) -> int:
    """Assign the event to the actual venue city, not blindly to the city used in the search query."""
    venue_city_name = venue.get("city", {}).get("name") if isinstance(venue, dict) else None
    if venue_city_name:
        row = fetch_one("SELECT id FROM cities WHERE LOWER(name) = LOWER(%s)", (venue_city_name,))
        if row:
            return row["id"]

        normalized_venue_city = normalize_city_name(venue_city_name)
        cities = fetch_all("SELECT id, name, latitude::float, longitude::float FROM cities")
        for city in cities:
            if normalize_city_name(city["name"]) == normalized_venue_city:
                return city["id"]

    if lat is not None and lon is not None:
        cities = fetch_all("SELECT id, name, latitude::float, longitude::float FROM cities")
        if cities:
            nearest = min(cities, key=lambda c: haversine_km(lat, lon, float(c["latitude"]), float(c["longitude"])))
            distance = haversine_km(lat, lon, float(nearest["latitude"]), float(nearest["longitude"]))
            if distance <= 75:
                return nearest["id"]

    return query_city_id


def ensure_venue(city_id: int, venue_name: str | None, lat: float | None, lon: float | None, address: str | None, source: str) -> int | None:
    if not venue_name:
        return None

    osm_id = f"ticketmaster-{city_id}-{venue_name.lower().replace(' ', '-')}"
    existing = fetch_one(
        "SELECT id FROM venues WHERE city_id = %s AND LOWER(name) = LOWER(%s)",
        (city_id, venue_name),
    )
    if existing:
        execute(
            """
            UPDATE venues
            SET latitude = COALESCE(%s, latitude),
                longitude = COALESCE(%s, longitude),
                address = COALESCE(%s, address),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (lat, lon, address, existing["id"]),
        )
        return existing["id"]

    execute(
        """
        INSERT INTO venues (osm_id, city_id, name, venue_type, latitude, longitude, address, source)
        VALUES (%s, %s, %s, 'music_venue', %s, %s, %s, %s)
        ON CONFLICT (osm_id, source) DO NOTHING
        """,
        (osm_id, city_id, venue_name, lat, lon, address, source),
    )
    row = fetch_one("SELECT id FROM venues WHERE city_id = %s AND LOWER(name) = LOWER(%s)", (city_id, venue_name))
    return row["id"] if row else None


@app.get("/events")
def get_events(
    city_id: int | None = None,
    genre: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    upcoming_only: bool = True,
    limit: int = Query(50, ge=1, le=200),
):
    params = []
    filters = []

    if city_id is not None:
        filters.append("e.city_id = %s")
        params.append(city_id)

    if genre and genre.lower() != "all":
        filters.append("(LOWER(e.genre_raw) = LOWER(%s) OR LOWER(COALESCE(at.main_genre, '')) = LOWER(%s))")
        params.extend([genre, genre])

    if date_from:
        filters.append("e.event_date >= %s")
        params.append(date_from)
    elif upcoming_only:
        filters.append("e.event_date >= CURRENT_DATE")

    if date_to:
        filters.append("e.event_date <= %s")
        params.append(date_to)

    where = "WHERE " + " AND ".join(filters) if filters else ""
    params.append(limit)

    return fetch_all(
        f"""
        SELECT
            e.id,
            e.city_id,
            e.name,
            e.event_date::text,
            e.event_time::text,
            e.url,
            e.genre_raw,
            e.subgenre_raw,
            c.name AS city_name,
            v.id AS venue_id,
            v.name AS venue_name,
            a.id AS artist_id,
            a.name AS artist_name,
            a.popularity::float AS artist_popularity,
            COALESCE(at.main_genre, e.genre_raw) AS main_genre,
            e.latitude::float,
            e.longitude::float
        FROM events e
        JOIN cities c ON c.id = e.city_id
        LEFT JOIN venues v ON v.id = e.venue_id
        LEFT JOIN artists a ON a.id = e.artist_id
        LEFT JOIN LATERAL (
            SELECT main_genre
            FROM artist_tags
            WHERE artist_id = a.id
            ORDER BY
                CASE WHEN source = 'Last.fm' THEN 0 ELSE 1 END,
                tag_weight DESC NULLS LAST,
                id
            LIMIT 1
        ) at ON true
        {where}
        ORDER BY e.event_date ASC, e.event_time ASC, e.id ASC
        LIMIT %s
        """,
        tuple(params),
    )
