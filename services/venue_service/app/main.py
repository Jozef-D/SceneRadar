import time
from typing import Any

import requests
from fastapi import FastAPI, Query

from services._shared.config import OVERPASS_URL
from services._shared.db import execute, fetch_all
from services._shared.http import add_cors
from services._shared.logging_utils import configure_logging

logger = configure_logging("venue-service")
app = FastAPI(title="SceneRadar Venue Service", version="1.0.0")
add_cors(app)

VENUE_TAGS = ["club", "nightclub", "music_venue", "concert_hall", "theatre", "bar", "arts_centre"]


@app.get("/venues/health")
def health():
    return {"status": "ok", "service": "venue-service"}


@app.get("/venues")
def get_venues(city_id: int | None = None):
    if city_id:
        return fetch_all(
            """
            SELECT v.id, v.name, v.venue_type, v.latitude::float, v.longitude::float, v.address, c.name AS city_name
            FROM venues v
            JOIN cities c ON c.id = v.city_id
            WHERE v.city_id = %s
            ORDER BY v.name
            """,
            (city_id,),
        )
    return fetch_all(
        """
        SELECT v.id, v.name, v.venue_type, v.latitude::float, v.longitude::float, v.address, c.name AS city_name
        FROM venues v
        JOIN cities c ON c.id = v.city_id
        ORDER BY c.name, v.name
        """
    )


@app.get("/venues/density")
def venue_density(city_id: int):
    row = fetch_all("SELECT COUNT(*) AS venue_count FROM venues WHERE city_id = %s", (city_id,))[0]
    return {"city_id": city_id, "venue_count": row["venue_count"]}


def overpass_query(lat: float, lon: float, radius: int) -> str:
    return f"""
    [out:json][timeout:18];
    (
      node(around:{radius},{lat},{lon})["amenity"~"^(nightclub|theatre|arts_centre|bar)$"]["name"];
      way(around:{radius},{lat},{lon})["amenity"~"^(nightclub|theatre|arts_centre|bar)$"]["name"];
      relation(around:{radius},{lat},{lon})["amenity"~"^(nightclub|theatre|arts_centre|bar)$"]["name"];

      node(around:{radius},{lat},{lon})["leisure"~"^(dance|music_venue)$"]["name"];
      way(around:{radius},{lat},{lon})["leisure"~"^(dance|music_venue)$"]["name"];
      relation(around:{radius},{lat},{lon})["leisure"~"^(dance|music_venue)$"]["name"];

      node(around:{radius},{lat},{lon})["music"]["name"];
      way(around:{radius},{lat},{lon})["music"]["name"];
      relation(around:{radius},{lat},{lon})["music"]["name"];
    );
    out center tags 80;
    """


def element_coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None, None


def venue_type_from_tags(tags: dict[str, Any]) -> str:
    amenity = tags.get("amenity")
    leisure = tags.get("leisure")
    if amenity in VENUE_TAGS:
        return amenity
    if leisure in VENUE_TAGS:
        return leisure
    if tags.get("music"):
        return "music_venue"
    return "venue"


def address_from_tags(tags: dict[str, Any], city_name: str) -> str:
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    city = tags.get("addr:city") or city_name
    parts = []
    if street:
        parts.append(f"{street} {number}".strip() if number else street)
    parts.append(city)
    parts.append("Polska")
    return ", ".join([p for p in parts if p])


def upsert_osm_venue(city_id: int, city_name: str, element: dict[str, Any]) -> int:
    tags = element.get("tags") or {}
    name = tags.get("name")
    if not name:
        return 0
    lat, lon = element_coordinates(element)
    osm_id = f"{element.get('type')}/{element.get('id')}"
    venue_type = venue_type_from_tags(tags)
    address = address_from_tags(tags, city_name)

    execute(
        """
        INSERT INTO venues (osm_id, city_id, name, venue_type, latitude, longitude, address, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'OpenStreetMap')
        ON CONFLICT (osm_id, source) DO UPDATE SET
            name = EXCLUDED.name,
            venue_type = EXCLUDED.venue_type,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            address = EXCLUDED.address,
            updated_at = CURRENT_TIMESTAMP
        """,
        (osm_id, city_id, name, venue_type, lat, lon, address),
    )
    return 1


@app.post("/venues/refresh")
def refresh_venues(radius: int = Query(7000, ge=1000, le=30000)):
    """Fetch real venue/map data from OpenStreetMap through Overpass API."""
    started = time.time()
    cities = fetch_all("SELECT id, name, latitude::float, longitude::float FROM cities ORDER BY id")
    fetched = 0
    saved = 0
    errors = 0

    city_results: list[dict[str, Any]] = []
    error_messages: list[str] = []
    for city in cities:
        try:
            logger.info("Fetching Overpass venues for city=%s radius=%s", city["name"], radius)
            response = requests.post(
                OVERPASS_URL,
                data={"data": overpass_query(city["latitude"], city["longitude"], radius)},
                timeout=25,
                headers={"User-Agent": "SceneRadarStudentProject/1.0"},
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])
            fetched += len(elements)
            city_saved = 0
            for element in elements:
                city_saved += upsert_osm_venue(city["id"], city["name"], element)
            saved += city_saved
            city_results.append({"city": city["name"], "fetched": len(elements), "saved": city_saved})
            time.sleep(0.4)
        except Exception as exc:
            message = f"{city['name']}: {exc}"
            logger.warning("Overpass fetch failed: %s", message)
            error_messages.append(message)
            city_results.append({"city": city["name"], "status": "error", "message": str(exc)})
            errors += 1

    duration_ms = int((time.time() - started) * 1000)
    execute(
        """
        INSERT INTO ingestion_logs (service_name, source_name, status, records_fetched, records_saved, error_message, started_at, finished_at, duration_ms)
        VALUES ('venue-service', 'OpenStreetMap/Overpass', %s, %s, %s, %s, NOW() - (%s || ' milliseconds')::interval, NOW(), %s)
        """,
        ("success" if errors == 0 else "partial", fetched, saved, None if errors == 0 else "; ".join(error_messages), duration_ms, duration_ms),
    )
    return {"status": "ok" if errors == 0 else "partial", "source": "OpenStreetMap/Overpass", "records_fetched": fetched, "records_saved": saved, "errors": error_messages, "cities": city_results}
