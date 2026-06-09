# Testy

Projekt zawiera:

- testy jednostkowe scoringu,
- testy mapowania gatunków,
- test wydajnościowy Locust.

Uruchomienie:

```bash
python -m pytest tests/unit
```

Albo przez Docker:

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```
