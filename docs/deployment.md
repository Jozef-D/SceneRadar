# Deployment

## Local run

```powershell
copy .env.example .env
docker compose down -v
docker compose build --no-cache
docker compose up
```

Fill `.env` before running refresh:

```env
TICKETMASTER_API_KEY=
LASTFM_API_KEY=
MUSICBRAINZ_CONTACT_EMAIL=
```

## URLs

- Frontend: `http://localhost:3000`
- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/health`
