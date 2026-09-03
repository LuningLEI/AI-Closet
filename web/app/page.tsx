"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import AuthGate from "../components/AuthGate";
import { apiClient, TodayRecommendationQuery } from "../lib/api-client";
import { useAuth } from "../lib/auth";
import { GEOLOCATION_MAX_AGE_MS, GEOLOCATION_TIMEOUT_MS, WEATHER_SOURCE } from "../lib/constants";
import { LOCATION_OPTIONS, LocationOption } from "../lib/location-presets";
import { OutfitRecommendation, TodayRecommendationResponse, UserPreferences } from "../types";

export default function HomePage() {
  const { configured, loading: authLoading, session } = useAuth();
  const canUsePrivateApi = !configured || (!authLoading && Boolean(session));
  const [today, setToday] = useState<TodayRecommendationResponse | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [preciseLoading, setPreciseLoading] = useState(false);
  const [selectedLocation, setSelectedLocation] = useState(LOCATION_OPTIONS[0].label);
  const [customLocationOption, setCustomLocationOption] = useState<LocationOption | null>(null);
  const [locationStatus, setLocationStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  useEffect(() => {
    if (canUsePrivateApi) {
      loadSavedPreference();
    }
  }, [canUsePrivateApi]);

  const activeRecommendation = today?.recommendations[activeIndex] ?? null;
  const weatherLabel = useMemo(() => {
    if (!today) return "Weather loading";
    return `${formatTemperature(today.weather.feels_like_f)} · ${today.weather.condition}`;
  }, [today]);

  async function loadTodayOutfit(options: { precise?: boolean; locationOption?: LocationOption } = {}) {
    const requestId = requestSequence.current + 1;
    requestSequence.current = requestId;
    setLoading(true);
    setError(null);
    try {
      let position: BrowserPosition | null = null;
      let query: TodayRecommendationQuery | undefined;
      if (options.precise) {
        setPreciseLoading(true);
        setLocationStatus("Requesting precise browser location...");
        position = await getBrowserPosition();
        if (requestId !== requestSequence.current) return;
        setLocationStatus(position ? `Precise location received, accuracy about ${Math.round(position.accuracy)}m.` : "Browser location unavailable. Using network location.");
        query = position ? { latitude: position.latitude, longitude: position.longitude } : undefined;
      } else if (options.locationOption) {
        query = {
          latitude: options.locationOption.latitude,
          longitude: options.locationOption.longitude,
          location_label: options.locationOption.label,
        };
        setLocationStatus(`Using "${options.locationOption.label}" as the weather location.`);
      } else {
        setLocationStatus("Using network location. Use precise location for better weather.");
      }
      const payload = await apiClient.recommendations.today(query);
      if (requestId !== requestSequence.current) return;
      setToday(payload);
      setActiveIndex(0);
      if (options.precise) {
        const preciseLocation = {
          label: payload.location.label,
          latitude: payload.location.latitude,
          longitude: payload.location.longitude,
        };
        setCustomLocationOption(preciseLocation);
        setSelectedLocation(preciseLocation.label);
        saveLocationPreference(preciseLocation).catch(() => {
          setLocationStatus("Precise location is applied, but saving the preference failed.");
        });
      }
    } catch (nextError) {
      if (requestId !== requestSequence.current) return;
      setError(nextError instanceof Error ? nextError.message : "Failed to load today's outfit.");
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false);
        setPreciseLoading(false);
      }
    }
  }

  async function loadSavedPreference() {
    try {
      const preferences = await apiClient.preferences.get();
      const savedLocation =
        preferences.default_location_label && preferences.default_latitude != null && preferences.default_longitude != null
          ? {
              label: preferences.default_location_label,
              latitude: preferences.default_latitude,
              longitude: preferences.default_longitude,
          }
          : LOCATION_OPTIONS[0];
      if (!LOCATION_OPTIONS.some((location) => location.label === savedLocation.label)) {
        setCustomLocationOption(savedLocation);
      }
      setSelectedLocation(savedLocation.label);
      await loadTodayOutfit({ locationOption: savedLocation });
    } catch {
      await loadTodayOutfit({ locationOption: LOCATION_OPTIONS[0] });
    }
  }

  async function saveLocationPreference(location: LocationOption) {
    await apiClient.preferences.update({
      default_location_label: location.label,
      default_latitude: location.latitude,
      default_longitude: location.longitude,
      temperature_unit: "F",
    });
  }

  function goPrevious() {
    if (!today?.recommendations.length) return;
    setActiveIndex(activeIndex === 0 ? today.recommendations.length - 1 : activeIndex - 1);
  }

  function goNext() {
    if (!today?.recommendations.length) return;
    setActiveIndex(activeIndex === today.recommendations.length - 1 ? 0 : activeIndex + 1);
  }

  const selectedLocationOption =
    LOCATION_OPTIONS.find((location) => location.label === selectedLocation) ??
    (customLocationOption?.label === selectedLocation ? customLocationOption : LOCATION_OPTIONS[0]);
  const renderedLocationOptions = LOCATION_OPTIONS.some((location) => location.label === selectedLocation)
    ? LOCATION_OPTIONS
    : [selectedLocationOption, ...LOCATION_OPTIONS];

  return (
    <AuthGate>
      <section className="page-shell">
      <header className="page-header today-hero">
        <div>
          <p className="eyebrow">Today</p>
          <h1>Today&apos;s outfit</h1>
          <p className="lead compact">
            Uses your current weather context and ML closet embeddings to recommend what to wear today.
          </p>
        </div>
        <div className="today-actions">
          <button className="button secondary" type="button" onClick={() => loadTodayOutfit({ locationOption: selectedLocationOption })} disabled={loading}>
            {loading && !preciseLoading ? "Refreshing..." : "Refresh"}
          </button>
          <button className="button primary" type="button" onClick={() => loadTodayOutfit({ precise: true })} disabled={loading}>
            {preciseLoading ? "Locating..." : "Use precise location"}
          </button>
        </div>
      </header>

      <div className="today-layout">
        <section className="panel today-weather-panel">
          <p className="section-label">Weather context</p>
          <h2>{weatherLabel}</h2>
          <form
            className="location-form"
            onSubmit={async (event) => {
              event.preventDefault();
              try {
                await saveLocationPreference(selectedLocationOption);
              } catch {
                setLocationStatus("Location is applied, but saving the preference failed.");
              }
              loadTodayOutfit({ locationOption: selectedLocationOption });
            }}
          >
            <label htmlFor="selected-location">Set location</label>
            <div>
              <select
                id="selected-location"
                value={selectedLocation}
                onChange={(event) => setSelectedLocation(event.target.value)}
              >
                {renderedLocationOptions.map((location) => (
                  <option key={location.label} value={location.label}>
                    {location.label}
                  </option>
                ))}
              </select>
              <button className="button secondary" type="submit" disabled={loading}>
                Apply
              </button>
            </div>
          </form>
          <dl className="today-weather-grid">
            <div>
              <dt>Location</dt>
              <dd>
                {today?.location.label || "Location unavailable"}
                {today?.location.detail ? <span>{today.location.detail}</span> : null}
              </dd>
            </div>
            <div>
              <dt>Temperature</dt>
              <dd>{today ? formatTemperature(today.weather.temperature_f) : "--"}</dd>
            </div>
            <div>
              <dt>Feels like</dt>
              <dd>{today ? formatTemperature(today.weather.feels_like_f) : "--"}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>
                {today?.weather.source || "unknown"}
                {today?.location.source ? <span>{sourceLabel(today.location.source)}</span> : null}
              </dd>
            </div>
          </dl>
          {locationStatus ? <p className="status-muted compact-status">{locationStatus}</p> : null}
        </section>

        <section className="panel today-outfit-panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Recommendation</p>
              <h2>Wear this today</h2>
            </div>
            {today?.recommendations.length ? (
              <span className="metric-badge">
                {activeIndex + 1} / {today.recommendations.length}
              </span>
            ) : null}
          </div>

          {loading && <p className="status-muted">Finding your location, reading weather, and scoring outfits...</p>}
          {error && <p className="status-error">{error}</p>}
          {!loading && today?.recommendations.length === 0 && (
            <div className="empty-today-state">
              <p className="status-muted">
                No recommendation-ready items yet. Upload clothes, run the recognition worker, then backfill embeddings.
              </p>
              <Link className="button primary" href="/closet">
                Open Closet
              </Link>
            </div>
          )}

          {activeRecommendation && (
            <div className="today-carousel">
              <button className="arrow-button arrow-button-left" type="button" onClick={goPrevious} aria-label="Previous outfit">
                ←
              </button>
              <TodayOutfitCard recommendation={activeRecommendation} />
              <button className="arrow-button arrow-button-right" type="button" onClick={goNext} aria-label="Next outfit">
                →
              </button>
            </div>
          )}
        </section>
      </div>
      </section>
    </AuthGate>
  );
}

function TodayOutfitCard({ recommendation }: { recommendation: OutfitRecommendation }) {
  const stylingNotes = recommendation.styling_notes ?? [];

  return (
    <article className="today-outfit-card">
      <div className="today-outfit-images">
        {recommendation.items.map((item) => (
          <img key={item.id} src={item.image_url} alt={item.subtype ?? item.category} />
        ))}
      </div>
      <div className="today-outfit-details">
        <p className="item-kicker">Match score {Math.round(recommendation.score)}</p>
        <h3>{recommendation.title}</h3>
        <ul className="reason-list">
          {recommendation.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        {stylingNotes.length > 0 && (
          <ul className="reason-list subtle-list">
            {stylingNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

interface BrowserPosition {
  latitude: number;
  longitude: number;
  accuracy: number;
}

function getBrowserPosition(): Promise<BrowserPosition | null> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return Promise.resolve(null);
  }

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        });
      },
      () => resolve(null),
      { enableHighAccuracy: true, maximumAge: GEOLOCATION_MAX_AGE_MS, timeout: GEOLOCATION_TIMEOUT_MS },
    );
  });
}

function sourceLabel(source: string) {
  if (source === WEATHER_SOURCE.BROWSER_GEOLOCATION) return "browser GPS/Wi-Fi location";
  if (source === WEATHER_SOURCE.IP_GEOLOCATION) return "network/IP location";
  if (source === WEATHER_SOURCE.MANUAL_LOCATION) return "manual location";
  return "fallback location";
}

function formatTemperature(fahrenheit: number) {
  const celsius = ((fahrenheit - 32) * 5) / 9;
  return `${Math.round(fahrenheit)}F / ${Math.round(celsius)}C`;
}
