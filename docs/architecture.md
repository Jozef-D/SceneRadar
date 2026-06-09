# Architecture — SceneRadar full API mode

SceneRadar uses a lightweight microservice architecture.

```mermaid
flowchart LR
    FE[Frontend React/Vite] --> GW[API Gateway FastAPI]
    GW --> C[City Service]
    GW --> E[Events Service]
    GW --> A[Artist Service]
    GW --> G[Genre Service]
    GW --> V[Venue Service]
    GW --> S[Scoring Service]

    E --> TM[Ticketmaster Discovery API]
    A --> MB[MusicBrainz API]
    G --> LF[Last.fm API]
    V --> OP[OpenStreetMap / Overpass API]

    C --> DB[(PostgreSQL)]
    E --> DB
    A --> DB
    G --> DB
    V --> DB
    S --> DB
```

## Services

- `events-service`: imports real upcoming music events from Ticketmaster.
- `artist-service`: resolves imported artists through MusicBrainz.
- `genre-service`: imports Last.fm tags and popularity.
- `venue-service`: imports real map venues from Overpass and also exposes Ticketmaster venues saved by events ingestion.
- `scoring-service`: calculates SceneRadar Score.
- `api-gateway`: public REST layer for frontend.
- `frontend`: visual user interface.

No artificial events, artists, tags, venues or city scores are inserted during database initialization.
