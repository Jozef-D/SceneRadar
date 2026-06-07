import time
from typing import Any

import psycopg2
import psycopg2.extras

from services._shared.config import DB_CONFIG


def get_connection(retries: int = 15, delay: float = 1.0):
    last_error = None
    for _ in range(retries):
        try:
            return psycopg2.connect(**DB_CONFIG)
        except psycopg2.OperationalError as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to database after {retries} retries: {last_error}")


def fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(row) for row in cur.fetchall()]


def fetch_one(sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return dict(row) if row else None


def execute(sql: str, params: tuple[Any, ...] | None = None) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            affected = cur.rowcount
        conn.commit()
        return affected


def execute_many(sql: str, rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
            affected = cur.rowcount
        conn.commit()
        return affected
