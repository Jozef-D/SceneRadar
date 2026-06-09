# API documentation — SceneRadar full API mode

Main public API is exposed through API Gateway at `http://localhost:8000`.

## Endpoints

```http
GET  /api/health
GET  /api/cities
GET  /api/genres
GET  /api/ranking?genre=metal
GET  /api/dashboard/{city_id}?genre=metal
GET  /api/cities/{city_id}/events?genre=metal
GET  /api/cities/{city_id}/venues
POST /api/refresh
```

## API keys

Real data ingestion requires:

```env
TICKETMASTER_API_KEY=
LASTFM_API_KEY=
MUSICBRAINZ_CONTACT_EMAIL=
```

MusicBrainz and Overpass do not require API keys, but MusicBrainz expects a meaningful User-Agent/contact.


## Debug/partial refresh endpoints

```http
POST /api/refresh/events
POST /api/refresh/venues
POST /api/refresh/genres
POST /api/refresh/artists
POST /api/refresh/scores
GET  /api/ingestion-logs
```

Use these endpoints when the full refresh is slow or when one external API fails.
