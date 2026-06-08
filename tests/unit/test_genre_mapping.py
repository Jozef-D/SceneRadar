from services._shared.genres import map_tag_to_genre


def test_metal_tag_mapping():
    assert map_tag_to_genre("thrash metal") == "metal"


def test_rap_tag_mapping():
    assert map_tag_to_genre("polish hip-hop") == "rap"


def test_unknown_tag_returns_none():
    assert map_tag_to_genre("unknown experimental tag") is None
