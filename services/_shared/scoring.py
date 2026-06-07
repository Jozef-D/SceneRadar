from dataclasses import dataclass


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def event_score(event_count: int) -> float:
    if event_count <= 0:
        return 0.0
    return clamp((event_count / 12.0) * 100.0)


def venue_score(venue_count: int) -> float:
    if venue_count <= 0:
        return 0.0
    return clamp((venue_count / 15.0) * 100.0)


def diversity_score(unique_subgenres: int) -> float:
    if unique_subgenres <= 0:
        return 0.0
    return clamp((unique_subgenres / 5.0) * 100.0)


def final_score(
    event_score_value: float,
    venue_score_value: float,
    artist_popularity_score_value: float,
    genre_diversity_score_value: float,
) -> float:
    return round(
        0.40 * event_score_value
        + 0.25 * venue_score_value
        + 0.20 * artist_popularity_score_value
        + 0.15 * genre_diversity_score_value,
        2,
    )


@dataclass
class ScoreBreakdown:
    event_score: float
    venue_score: float
    artist_popularity_score: float
    genre_diversity_score: float
    final_score: float
