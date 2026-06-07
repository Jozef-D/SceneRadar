SUPPORTED_GENRES = [
    "metal",
    "rap",
    "jazz",
    "indie",
    "pop",
    "electronic",
    "techno",
]

PUBLIC_GENRES = ["all"] + SUPPORTED_GENRES

GENRE_ALIASES = {
    # rock / metal bucket
    "metal": "metal",
    "heavy metal": "metal",
    "black metal": "metal",
    "death metal": "metal",
    "thrash metal": "metal",
    "doom metal": "metal",
    "power metal": "metal",
    "progressive metal": "metal",
    "symphonic metal": "metal",
    "hard rock": "metal",
    "rock": "metal",
    "classic rock": "metal",
    "alternative rock": "metal",
    "punk": "metal",
    "punk rock": "metal",
    "hardcore": "metal",

    # rap / hip-hop
    "rap": "rap",
    "hip hop": "rap",
    "hip-hop": "rap",
    "polish hip-hop": "rap",
    "trap": "rap",
    "urban": "rap",

    # jazz
    "jazz": "jazz",
    "blues": "jazz",
    "swing": "jazz",
    "jazz fusion": "jazz",
    "smooth jazz": "jazz",

    # indie
    "indie": "indie",
    "indie rock": "indie",
    "indie pop": "indie",
    "alternative": "indie",
    "alternative/indie rock": "indie",

    # pop
    "pop": "pop",
    "dance pop": "pop",
    "r&b": "pop",
    "rnb": "pop",
    "soul": "pop",
    "latin": "pop",

    # electronic / techno
    "electronic": "electronic",
    "electronica": "electronic",
    "edm": "electronic",
    "dance": "electronic",
    "house": "electronic",
    "drum and bass": "electronic",
    "dnb": "electronic",
    "ambient": "electronic",
    "trance": "electronic",
    "techno": "techno",
    "minimal techno": "techno",
    "industrial techno": "techno",
}


def normalize_tag(tag: str | None) -> str:
    if not tag:
        return ""
    return " ".join(str(tag).strip().lower().replace("_", " ").split())


def map_tag_to_genre(tag: str | None) -> str | None:
    normalized = normalize_tag(tag)
    if not normalized:
        return None

    if normalized in GENRE_ALIASES:
        return GENRE_ALIASES[normalized]

    # Looser matching for inconsistent Ticketmaster / Last.fm labels.
    ordered_aliases = sorted(GENRE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, genre in ordered_aliases:
        if alias and alias in normalized:
            return genre

    if "concert" in normalized or "koncert" in normalized or "live" in normalized:
        return "pop"

    return None
