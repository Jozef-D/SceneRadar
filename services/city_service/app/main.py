from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services._shared.db import execute, fetch_all, fetch_one
from services._shared.http import add_cors
from services._shared.logging_utils import configure_logging

logger = configure_logging("city-service")
app = FastAPI(title="SceneRadar City Service", version="1.0.0")
add_cors(app)


class CityCreate(BaseModel):
    name: str
    country: str = "Poland"
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "city-service"}


@app.get("/cities")
def get_cities():
    return fetch_all(
        """
        SELECT id, name, country, region, latitude::float, longitude::float
        FROM cities
        ORDER BY name
        """
    )


@app.get("/cities/{city_id}")
def get_city(city_id: int):
    city = fetch_one(
        """
        SELECT id, name, country, region, latitude::float, longitude::float
        FROM cities WHERE id = %s
        """,
        (city_id,),
    )
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    return city


@app.post("/cities", status_code=201)
def create_city(city: CityCreate):
    execute(
        """
        INSERT INTO cities (name, country, region, latitude, longitude)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            country = EXCLUDED.country,
            region = EXCLUDED.region,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            updated_at = CURRENT_TIMESTAMP
        """,
        (city.name, city.country, city.region, city.latitude, city.longitude),
    )
    logger.info("City saved: %s", city.name)
    return {"status": "saved", "city": city.name}
