CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    country VARCHAR(100) NOT NULL DEFAULT 'Poland',
    region VARCHAR(100),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS venues (
    id SERIAL PRIMARY KEY,
    osm_id VARCHAR(100),
    city_id INTEGER REFERENCES cities(id),
    name VARCHAR(255),
    venue_type VARCHAR(100),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    address TEXT,
    source VARCHAR(100) DEFAULT 'OpenStreetMap',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(osm_id, source)
);

CREATE TABLE IF NOT EXISTS artists (
    id SERIAL PRIMARY KEY,
    mbid VARCHAR(100),
    name VARCHAR(255) NOT NULL UNIQUE,
    sort_name VARCHAR(255),
    country VARCHAR(100),
    artist_type VARCHAR(100),
    popularity NUMERIC(5,2),
    disambiguation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(255),
    name VARCHAR(255) NOT NULL,
    city_id INTEGER REFERENCES cities(id),
    venue_id INTEGER REFERENCES venues(id),
    artist_id INTEGER REFERENCES artists(id),
    event_date DATE,
    event_time TIME,
    category VARCHAR(100),
    genre_raw VARCHAR(100),
    subgenre_raw VARCHAR(100),
    artist_name_raw VARCHAR(255),
    source VARCHAR(100),
    url TEXT,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(external_id, source)
);

CREATE TABLE IF NOT EXISTS artist_tags (
    id SERIAL PRIMARY KEY,
    artist_id INTEGER REFERENCES artists(id),
    tag_name VARCHAR(100),
    tag_weight NUMERIC(6, 2),
    main_genre VARCHAR(100),
    source VARCHAR(100) DEFAULT 'Last.fm',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(artist_id, tag_name, source)
);

CREATE TABLE IF NOT EXISTS city_scores (
    id SERIAL PRIMARY KEY,
    city_id INTEGER REFERENCES cities(id),
    genre VARCHAR(100),
    date_from DATE,
    date_to DATE,
    event_score NUMERIC(5, 2),
    venue_score NUMERIC(5, 2),
    artist_popularity_score NUMERIC(5, 2),
    genre_diversity_score NUMERIC(5, 2),
    final_score NUMERIC(5, 2),
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_logs (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100),
    source_name VARCHAR(100),
    status VARCHAR(50),
    records_fetched INTEGER,
    records_saved INTEGER,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INTEGER
);

INSERT INTO cities (id, name, region, latitude, longitude) VALUES
    (1, 'Warszawa', 'Mazowieckie', 52.2297, 21.0122),
    (2, 'Kraków', 'Małopolskie', 50.0647, 19.9450),
    (3, 'Wrocław', 'Dolnośląskie', 51.1079, 17.0385),
    (4, 'Gdańsk', 'Pomorskie', 54.3520, 18.6466),
    (5, 'Poznań', 'Wielkopolskie', 52.4064, 16.9252),
    (6, 'Łódź', 'Łódzkie', 51.7592, 19.4560),
    (7, 'Katowice', 'Śląskie', 50.2649, 19.0238),
    (8, 'Lublin', 'Lubelskie', 51.2465, 22.5684)
ON CONFLICT (name) DO UPDATE SET
    region = EXCLUDED.region,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    updated_at = CURRENT_TIMESTAMP;

SELECT setval('cities_id_seq', (SELECT MAX(id) FROM cities));
