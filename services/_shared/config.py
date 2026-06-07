import os


def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


DB_CONFIG = {
    "dbname": env("POSTGRES_DB", "sceneradar"),
    "user": env("POSTGRES_USER", "sceneradar"),
    "password": env("POSTGRES_PASSWORD", "sceneradar"),
    "host": env("POSTGRES_HOST", "postgres"),
    "port": int(env("POSTGRES_PORT", "5432") or 5432),
}

TICKETMASTER_API_KEY = env("TICKETMASTER_API_KEY", "")
LASTFM_API_KEY = env("LASTFM_API_KEY", "")
MUSICBRAINZ_APP_NAME = env("MUSICBRAINZ_APP_NAME", "SceneRadarStudentProject")
MUSICBRAINZ_CONTACT_EMAIL = env("MUSICBRAINZ_CONTACT_EMAIL", "")
OVERPASS_URL = env("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
