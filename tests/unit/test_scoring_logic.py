from services._shared.scoring import diversity_score, event_score, final_score, venue_score


def test_event_score_zero_events():
    assert event_score(0) == 0


def test_event_score_many_events_is_capped():
    assert event_score(99) == 100


def test_venue_score_scales_to_100():
    assert round(venue_score(15), 2) == 100


def test_diversity_score():
    assert diversity_score(5) == 100


def test_final_sceneradar_score():
    score = final_score(
        event_score_value=80,
        venue_score_value=70,
        artist_popularity_score_value=90,
        genre_diversity_score_value=60,
    )
    assert score == 76.5
