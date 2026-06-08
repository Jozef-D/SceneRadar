import React, { useEffect, useMemo, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const genreLabels = {
  all: 'Wszystkie',
  metal: 'Metal',
  techno: 'Techno',
  rap: 'Rap',
  jazz: 'Jazz',
  indie: 'Indie',
  pop: 'Pop',
  electronic: 'Electronic',
}

function scoreClass(score) {
  if (score >= 80) return 'scoreHigh'
  if (score >= 60) return 'scoreGood'
  if (score >= 40) return 'scoreMid'
  return 'scoreLow'
}

async function api(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, options)
  if (!response.ok) throw new Error(`API error ${response.status}`)
  return response.json()
}

export default function App() {
  const [genres, setGenres] = useState(['all', 'metal', 'techno', 'rap', 'jazz', 'indie', 'pop', 'electronic'])
  const [selectedGenre, setSelectedGenre] = useState('all')
  const [ranking, setRanking] = useState([])
  const [selectedCityId, setSelectedCityId] = useState(null)
  const [dashboard, setDashboard] = useState(null)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [rankingLoading, setRankingLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/api/genres').then(setGenres).catch(() => {})
  }, [])

  useEffect(() => {
    loadRanking(selectedGenre)
  }, [selectedGenre])

  useEffect(() => {
    if (ranking.length && !selectedCityId) setSelectedCityId(ranking[0].city_id)
  }, [ranking, selectedCityId])

  useEffect(() => {
    if (selectedCityId) loadDashboard(selectedCityId, selectedGenre)
  }, [selectedCityId, selectedGenre])

  async function loadRanking(genre) {
    setRankingLoading(true)
    setError('')
    try {
      const data = await api(`/api/ranking?genre=${encodeURIComponent(genre)}`)
      setRanking(data)
      if (data.length && !data.find((city) => city.city_id === selectedCityId)) {
        setSelectedCityId(data[0].city_id)
      }
    } catch (err) {
      setError('Nie udało się pobrać rankingu. Sprawdź, czy działa backend.')
    } finally {
      setRankingLoading(false)
    }
  }

  async function loadDashboard(cityId, genre) {
    setDashboardLoading(true)
    setDashboard(null)
    try {
      const data = await api(`/api/dashboard/${cityId}?genre=${encodeURIComponent(genre)}&events_limit=100`)
      setDashboard(data)
    } catch (err) {
      console.error(err)
      setError('Nie udało się pobrać danych miasta.')
    } finally {
      setDashboardLoading(false)
    }
  }

  async function refreshData() {
    setRefreshing(true)
    setError('')
    try {
      await api('/api/refresh', { method: 'POST' })
      await loadRanking(selectedGenre)
      if (selectedCityId) await loadDashboard(selectedCityId, selectedGenre)
    } catch (err) {
      setError('Odświeżanie danych nie powiodło się.')
    } finally {
      setRefreshing(false)
    }
  }

  const selectedCity = useMemo(
    () => ranking.find((city) => city.city_id === selectedCityId),
    [ranking, selectedCityId]
  )

  const visibleEvents = useMemo(() => {
    const cityName = dashboard?.city?.name
    return (dashboard?.events || []).filter((event) => {
      const cityOk = Number(event.city_id) === Number(selectedCityId) || event.city_name === cityName
      const genre = String(event.main_genre || event.genre_raw || '').toLowerCase()
      const genreOk = genre === selectedGenre.toLowerCase()
      return cityOk && genreOk
    })
  }, [dashboard, selectedCityId, selectedGenre])

  return (
    <div className="appShell">
      <div className="backdropGrid" />

      <section className="hero">
        <div className="heroText">
          <div className="heroTop">
            <h1>SceneRadar</h1>
            <button className="refreshButton" onClick={refreshData} disabled={refreshing}>
              {refreshing ? 'ODŚWIEŻANIE' : 'ODŚWIEŻ DANE'}
            </button>
          </div>
          <p>
            Radar lokalnych scen muzycznych do porównywania polskich miast według liczby
            koncertów, infrastruktury venue, popularności artystów i różnorodności gatunków.
          </p>
          <div className="genreTabs">
            {genres.map((genre) => (
              <button
                key={genre}
                className={genre === selectedGenre ? 'genreTab activeGenreTab' : 'genreTab'}
                onClick={() => setSelectedGenre(genre)}
              >
                {genreLabels[genre] || genre}
              </button>
            ))}
          </div>
        </div>
      </section>

      <main className="layoutGrid">
        <section className="sectionBlock rankingBlock">
          <div className="sectionHeader">
            <div>
              <div className="cardLabel">RANKING</div>
              <h2>{genreLabels[selectedGenre] || selectedGenre}</h2>
            </div>
            {rankingLoading && <span className="statusPill">ŁADOWANIE</span>}
          </div>

          {error && <div className="errorBox">{error}</div>}

          <div className="rankingList">
            {ranking.map((city, index) => (
              <button
                key={city.city_id}
                className={city.city_id === selectedCityId ? 'rankRow activeRankRow' : 'rankRow'}
                onClick={() => setSelectedCityId(city.city_id)}
              >
                <span className="rankNo">{String(index + 1).padStart(2, '0')}</span>
                <span className="rankCity">
                  <strong>{city.city_name}</strong>
                  <small>{city.region}</small>
                </span>
                <span className="rankBar"><i style={{ width: `${Math.max(6, city.final_score)}%` }} /></span>
                <span className={`rankScore ${scoreClass(city.final_score)}`}>{Math.round(city.final_score)}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="sectionBlock cityBlock">
          <div className="sectionHeader">
            <div>
              <div className="cardLabel">MIASTO</div>
              <h2>{selectedCity?.city_name || 'Wybierz miasto'}</h2>
            </div>
            <span className="statusPill">{genreLabels[selectedGenre] || selectedGenre}</span>
          </div>

          {dashboardLoading && <div className="loadingBox">Pobieranie danych wybranego miasta.</div>}

          {dashboard?.score && (
            <>
              <div className="metricsGrid">
                <Metric label="Wydarzenia" value={dashboard.score.event_score} />
                <Metric label="Venue" value={dashboard.score.venue_score} />
                <Metric label="Popularność" value={dashboard.score.artist_popularity_score} />
                <Metric label="Różnorodność" value={dashboard.score.genre_diversity_score} />
              </div>
              <div className="summaryBox">{dashboard.score.summary}</div>
              {dashboard.diagnostics && (
                <div className="diagnosticsGrid">
                  <div><span>Wydarzenia w mieście</span><strong>{dashboard.diagnostics.events_total_for_city}</strong></div>
                  <div><span>Widoczne po filtrze</span><strong>{dashboard.diagnostics.events_visible_after_filter}</strong></div>
                  <div><span>Venue</span><strong>{dashboard.diagnostics.venues_total_for_city}</strong></div>
                </div>
              )}
            </>
          )}

          <div className="listsGrid">
            <div className="listPanel">
              <div className="listHeader">
                <h3>Najbliższe wydarzenia</h3>
                <span>{visibleEvents.length}</span>
              </div>
              <div className="scrollList">
                {visibleEvents.length ? visibleEvents.map((event) => (
                  <EventCard event={event} key={event.id} />
                )) : (
                  <div className="emptyState">Brak wydarzeń dla wybranego miasta i gatunku.</div>
                )}
              </div>
            </div>

            <div className="listPanel">
              <div className="listHeader">
                <h3>Lista venues</h3>
                <span>{dashboard?.venues?.length || 0}</span>
              </div>
              <VenueList venues={dashboard?.venues || []} />
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

function Metric({ label, value }) {
  const rounded = Math.round(value || 0)
  return (
    <div className="metricCard">
      <span>{label}</span>
      <strong>{rounded}</strong>
      <div className="metricBar"><i style={{ width: `${rounded}%` }} /></div>
    </div>
  )
}

function EventCard({ event }) {
  const url = cleanEventUrl(event)
  const body = (
    <>
      <div className="dateTile">{formatDay(event.event_date)}</div>
      <div className="eventInfo">
        <strong>{event.name}</strong>
        <p>{event.venue_name || 'Venue nieznane'} / {event.artist_name || 'Artysta nieznany'}</p>
      </div>
      <span className="openMark">↗</span>
    </>
  )

  return url ? (
    <a className="eventCard clickableCard" href={url} target="_blank" rel="noreferrer">{body}</a>
  ) : (
    <div className="eventCard">{body}</div>
  )
}

function VenueList({ venues }) {
  if (!venues.length) return <div className="emptyState">Brak venue dla wybranego miasta.</div>

  return (
    <div className="scrollList venueList">
      {venues.map((venue) => (
        <a
          key={venue.id}
          className="venueCard clickableCard"
          href={googleMapsUrl(venue)}
          target="_blank"
          rel="noreferrer"
        >
          <div>
            <strong>{venue.name}</strong>
            <p>{[venue.address, venue.city_name].filter(Boolean).join(' / ') || 'Adres nieznany'}</p>
          </div>
          <span className="venueType">{formatVenueType(venue.venue_type)}</span>
          <span className="openMark">↗</span>
        </a>
      ))}
    </div>
  )
}

function formatDay(dateString) {
  if (!dateString) return '--'
  const date = new Date(dateString)
  return date.toLocaleDateString('pl-PL', { day: '2-digit', month: 'short' }).toUpperCase()
}

function formatVenueType(type) {
  if (!type) return 'VENUE'
  return String(type).replaceAll('_', ' ').toUpperCase()
}

function googleMapsUrl(venue) {
  const query = [venue.name, venue.address, venue.city_name, 'Polska']
    .filter(Boolean)
    .join(' ')
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`
}

function cleanEventUrl(event) {
  if (event.url) return event.url
  const query = [event.name, event.venue_name, event.city_name, 'koncert']
    .filter(Boolean)
    .join(' ')
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`
}
