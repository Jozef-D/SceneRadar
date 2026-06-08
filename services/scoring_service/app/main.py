from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query

from services._shared.db import execute, fetch_all, fetch_one
from services._shared.genres import PUBLIC_GENRES, SUPPORTED_GENRES
from services._shared.http import add_cors
from services._shared.logging_utils import configure_logging
from services._shared.scoring import diversity_score, event_score, final_score, venue_score

logger = configure_logging("scoring-service")
app = FastAPI(title="SceneRadar Scoring Service", version="1.0.0")
add_cors(app)


@app.get("/score/health")
def health():
    return {"status": "ok", "service": "scoring-service"}


def default_date_range() -> tuple[str, str]:
    start = date.today()
    end = start + timedelta(days=30)
    return start.isoformat(), end.isoformat()


@app.post("/score/recalculate")
def recalculate_scores(
    date_from: str | None = None,
    date_to: str | None = None,
):
    if not date_from or not date_to:
        date_from, date_to = default_date_range()
    execute("DELETE FROM city_scores WHERE date_from = %s AND date_to = %s", (date_from, date_to))
    cities = fetch_all("SELECT id, name FROM cities ORDER BY id")
    saved = 0
    for genre in PUBLIC_GENRES:
        for city in cities:
            breakdown = calculate_city_genre(city["id"], genre, date_from, date_to)
            summary = build_summary(city["name"], genre, breakdown)
            execute(
                """
                INSERT INTO city_scores
                (city_id, genre, date_from, date_to, event_score, venue_score, artist_popularity_score, genre_diversity_score, final_score, summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    city["id"], genre, date_from, date_to,
                    breakdown["event_score"], breakdown["venue_score"], breakdown["artist_popularity_score"],
                    breakdown["genre_diversity_score"], breakdown["final_score"], summary,
                ),
            )
            saved += 1
    logger.info("Recalculated %s scores", saved)
    return {"status": "ok", "scores_saved": saved}


def calculate_city_genre(city_id: int, genre: str, date_from: str, date_to: str):
    if genre == "all":
        row = fetch_one(
            """
            SELECT
                COUNT(DISTINCT e.id)::int AS event_count,
                COALESCE(AVG(COALESCE(a.popularity, 35.0)), 35.0)::float AS avg_popularity,
                COUNT(DISTINCT COALESCE(at.tag_name, e.genre_raw))::int AS tag_count
            FROM events e
            LEFT JOIN artists a ON a.id = e.artist_id
            LEFT JOIN artist_tags at ON at.artist_id = a.id
            WHERE e.city_id = %s
              AND e.event_date BETWEEN %s AND %s
            """,
            (city_id, date_from, date_to),
        ) or {"event_count": 0, "avg_popularity": 35, "tag_count": 0}
    else:
        row = fetch_one(
            """
            SELECT
                COUNT(DISTINCT e.id)::int AS event_count,
                COALESCE(AVG(COALESCE(a.popularity, 35.0)), 35.0)::float AS avg_popularity,
                COUNT(DISTINCT at.tag_name)::int AS tag_count
            FROM events e
            LEFT JOIN artists a ON a.id = e.artist_id
            LEFT JOIN artist_tags at ON at.artist_id = a.id
            WHERE e.city_id = %s
              AND (at.main_genre = %s OR LOWER(COALESCE(e.genre_raw, '')) = LOWER(%s))
              AND e.event_date BETWEEN %s AND %s
            """,
            (city_id, genre, genre, date_from, date_to),
        ) or {"event_count": 0, "avg_popularity": 35, "tag_count": 0}

    venue_row = fetch_one("SELECT COUNT(*)::int AS venue_count FROM venues WHERE city_id = %s", (city_id,))
    event_score_value = ticketmaster_event_score(row["event_count"])
    venue_score_value = venue_score(venue_row["venue_count"] if venue_row else 0)
    popularity = round(float(row["avg_popularity"] or 35.0), 2)
    genre_diversity = diversity_score(row["tag_count"])
    final = final_score(event_score_value, venue_score_value, popularity, genre_diversity)
    return {
        "event_count": row["event_count"],
        "venue_count": venue_row["venue_count"] if venue_row else 0,
        "event_score": round(event_score_value, 2),
        "venue_score": round(venue_score_value, 2),
        "artist_popularity_score": popularity,
        "genre_diversity_score": round(genre_diversity, 2),
        "final_score": final,
    }


def ticketmaster_event_score(event_count: int) -> float:
    # Ticketmaster-only mode has lower coverage in Poland, so the scale is less brutal.
    if event_count <= 0:
        return 0.0
    if event_count == 1:
        return 40.0
    if event_count <= 3:
        return 65.0
    if event_count <= 6:
        return 80.0
    return 100.0


def build_summary(city_name: str, genre: str, breakdown: dict) -> str:
    if breakdown["final_score"] >= 80:
        level = "bardzo mocną"
    elif breakdown["final_score"] >= 60:
        level = "aktywną"
    elif breakdown["final_score"] >= 40:
        level = "rozwijającą się"
    else:
        level = "raczej niszową"
    return (
        f"{city_name} ma {level} scenę muzyczną" + (f" ({genre})" if genre != "all" else "") + ": "
        f"{breakdown['event_count']} wydarzeń w analizowanym okresie, "
        f"{breakdown['venue_count']} venue oraz średnią popularność artystów "
        f"{breakdown['artist_popularity_score']:.1f}/100."
    )


@app.get("/score/ranking")
def ranking(
    genre: str = Query("metal"),
    date_from: str | None = None,
    date_to: str | None = None,
):
    if genre not in PUBLIC_GENRES:
        raise HTTPException(status_code=400, detail=f"Unsupported genre: {genre}")
    if not date_from or not date_to:
        date_from, date_to = default_date_range()
    params = [genre]
    date_filter = "AND cs.date_from = %s AND cs.date_to = %s"
    params.extend([date_from, date_to])
    rows = fetch_all(
        f"""
        SELECT
            c.id AS city_id,
            c.name AS city_name,
            c.region,
            c.latitude::float,
            c.longitude::float,
            cs.genre,
            cs.event_score::float,
            cs.venue_score::float,
            cs.artist_popularity_score::float,
            cs.genre_diversity_score::float,
            cs.final_score::float,
            cs.summary,
            cs.created_at::text
        FROM city_scores cs
        JOIN cities c ON c.id = cs.city_id
        WHERE cs.genre = %s {date_filter}
        ORDER BY cs.final_score DESC, c.name
        """,
        tuple(params),
    )
    if not rows:
        if not date_from or not date_to:
            date_from, date_to = default_date_range()
        recalculate_scores(date_from, date_to)
        return ranking(genre, date_from, date_to)
    return rows


@app.get("/score")
def city_score(
    city_id: int,
    genre: str = Query("metal"),
    date_from: str | None = None,
    date_to: str | None = None,
):
    if not date_from or not date_to:
        date_from, date_to = default_date_range()
    row = fetch_one(
        """
        SELECT
            c.id AS city_id,
            c.name AS city_name,
            cs.genre,
            cs.event_score::float,
            cs.venue_score::float,
            cs.artist_popularity_score::float,
            cs.genre_diversity_score::float,
            cs.final_score::float,
            cs.summary,
            cs.created_at::text
        FROM city_scores cs
        JOIN cities c ON c.id = cs.city_id
        WHERE cs.city_id = %s
          AND cs.genre = %s
          AND cs.date_from = %s
          AND cs.date_to = %s
        ORDER BY cs.created_at DESC
        LIMIT 1
        """,
        (city_id, genre, date_from, date_to),
    )
    if not row:
        recalculate_scores(date_from, date_to)
        row = fetch_one(
            """
            SELECT
                c.id AS city_id,
                c.name AS city_name,
                cs.genre,
                cs.event_score::float,
                cs.venue_score::float,
                cs.artist_popularity_score::float,
                cs.genre_diversity_score::float,
                cs.final_score::float,
                cs.summary,
                cs.created_at::text
            FROM city_scores cs
            JOIN cities c ON c.id = cs.city_id
            WHERE cs.city_id = %s
              AND cs.genre = %s
              AND cs.date_from = %s
              AND cs.date_to = %s
            ORDER BY cs.created_at DESC
            LIMIT 1
            """,
            (city_id, genre, date_from, date_to),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Score not found")
    return row
