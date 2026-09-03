"use client";

import { useState } from "react";
import AuthGate from "../../components/AuthGate";
import { apiClient } from "../../lib/api-client";
import {
  DEFAULT_OCCASION,
  DEFAULT_RECOMMENDATION_LIMIT,
  DEFAULT_TEMPERATURE_F,
  FILTER_ANY_VALUE,
  OCCASION_OPTIONS,
  RECOMMENDATION_COLOR_OPTIONS,
  STYLE_OPTIONS,
} from "../../lib/constants";
import { OutfitRecommendation, RecommendationsRequest, RecommendationsResponse } from "../../types";

export default function RecommendationsPage() {
  const [occasion, setOccasion] = useState(DEFAULT_OCCASION);
  const [preferredStyle, setPreferredStyle] = useState(FILTER_ANY_VALUE);
  const [preferredColor, setPreferredColor] = useState(FILTER_ANY_VALUE);
  const [temperatureF, setTemperatureF] = useState(DEFAULT_TEMPERATURE_F);
  const [result, setResult] = useState<RecommendationsResponse | null>(null);
  const [activeRecommendationIndex, setActiveRecommendationIndex] = useState(0);
  const [slideDirection, setSlideDirection] = useState<"next" | "previous">("next");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generateRecommendations() {
    setBusy(true);
    setError(null);
    try {
      const requestPayload: RecommendationsRequest = {
        occasion,
        preferred_style: preferredStyle === FILTER_ANY_VALUE ? null : preferredStyle,
        preferred_color: preferredColor === FILTER_ANY_VALUE ? null : preferredColor,
        temperature_f: temperatureF,
        limit: DEFAULT_RECOMMENDATION_LIMIT,
      };
      const payload = await apiClient.recommendations.create(requestPayload);
      setResult(payload);
      setActiveRecommendationIndex(0);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to generate recommendations.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthGate>
      <section className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Recommendations</p>
          <h1>Outfit scoring workspace</h1>
          <p className="lead compact">
            This mirrors the iOS recommendation engine: score combinations by occasion fit, temperature, style harmony,
            color harmony, and outfit completeness.
          </p>
        </div>
      </header>

      <div className="dashboard-grid recommendation-layout">
        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Inputs</p>
              <h2>Recommendation context</h2>
            </div>
          </div>
          <div className="control-grid">
            <label>
              Occasion
              <select value={occasion} onChange={(event) => setOccasion(event.target.value)}>
                {OCCASION_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Style preference
              <select value={preferredStyle} onChange={(event) => setPreferredStyle(event.target.value)}>
                {[FILTER_ANY_VALUE, ...STYLE_OPTIONS].map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Color preference
              <select value={preferredColor} onChange={(event) => setPreferredColor(event.target.value)}>
                {[FILTER_ANY_VALUE, ...RECOMMENDATION_COLOR_OPTIONS].map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Temperature
              <div className="range-row">
                <input
                  type="range"
                  min={20}
                  max={95}
                  step={1}
                  value={temperatureF}
                  onChange={(event) => setTemperatureF(Number(event.target.value))}
                />
                <span>{temperatureF}F</span>
              </div>
            </label>
          </div>
          <button className="button primary" onClick={generateRecommendations} type="button" disabled={busy}>
            {busy ? "Scoring..." : "Generate Recommendations"}
          </button>
          {error && <p className="status-error">{error}</p>}
        </section>

        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Results</p>
              <h2>Best outfit candidates</h2>
            </div>
          </div>
          {!result && <p className="status-muted">Run the scoring engine to see the top outfit combinations.</p>}
          {result?.recommendations.length === 0 && (
            <p className="status-muted">
              No recommendation-ready items yet. Upload clothes in Closet, then keep the recognition worker running until
              cards finish analyzing.
            </p>
          )}
          {result && result.recommendations.length > 0 && (
            <RecommendationCarousel
              recommendations={result.recommendations}
              activeIndex={activeRecommendationIndex}
              direction={slideDirection}
              onChange={(index, direction) => {
                setSlideDirection(direction);
                setActiveRecommendationIndex(index);
              }}
            />
          )}
        </section>
      </div>
      </section>
    </AuthGate>
  );
}

function RecommendationCarousel({
  recommendations,
  activeIndex,
  direction,
  onChange,
}: {
  recommendations: OutfitRecommendation[];
  activeIndex: number;
  direction: "next" | "previous";
  onChange: (index: number, direction: "next" | "previous") => void;
}) {
  const activeRecommendation = recommendations[activeIndex];
  const total = recommendations.length;

  function goPrevious() {
    onChange(activeIndex === 0 ? total - 1 : activeIndex - 1, "previous");
  }

  function goNext() {
    onChange(activeIndex === total - 1 ? 0 : activeIndex + 1, "next");
  }

  return (
    <div className="recommendation-carousel">
      <div className="carousel-status">
        <span>
          Recommendation {activeIndex + 1} of {total}
        </span>
      </div>

      <div className="carousel-stage">
        <button className="arrow-button arrow-button-left" type="button" onClick={goPrevious} aria-label="Previous recommendation">
          ←
        </button>
        <div key={activeRecommendation.id} className={`carousel-slide slide-${direction}`}>
          <RecommendationCard recommendation={activeRecommendation} />
        </div>
        <button className="arrow-button arrow-button-right" type="button" onClick={goNext} aria-label="Next recommendation">
          →
        </button>
      </div>

      <div className="carousel-dots" aria-label="Recommendation position">
        {recommendations.map((recommendation, index) => (
          <button
            key={recommendation.id}
            className={index === activeIndex ? "active" : ""}
            type="button"
            onClick={() => onChange(index, index > activeIndex ? "next" : "previous")}
            aria-label={`Show recommendation ${index + 1}`}
          />
        ))}
      </div>
    </div>
  );
}

function RecommendationCard({ recommendation }: { recommendation: OutfitRecommendation }) {
  const stylingNotes = recommendation.styling_notes ?? [];
  const breakdownEntries = [
    ["ML Fit", recommendation.breakdown.semantic_fit],
    ["Occasion", recommendation.breakdown.occasion_fit],
    ["Weather", recommendation.breakdown.weather_fit],
    ["Style", recommendation.breakdown.style_harmony],
    ["Color", recommendation.breakdown.color_harmony],
    ["Complete", recommendation.breakdown.category_balance],
  ] as const;

  return (
    <article className="recommendation-card">
      <div className="recommendation-header">
        <div>
          <p className="item-kicker">Match Score {Math.round(recommendation.score)}</p>
          <h3>{recommendation.title}</h3>
        </div>
        <div className="chip-row compact">
          {recommendation.items.map((item) => (
            <span key={item.id} className="pill subtle">
              {item.subtype ?? item.category}
            </span>
          ))}
        </div>
      </div>

      <div className="score-meter" aria-label={`Recommendation score ${Math.round(recommendation.score)}`}>
        <span style={{ width: `${Math.min(100, Math.round(recommendation.score))}%` }} />
      </div>

      <div className="recommendation-image-grid">
        {recommendation.items.map((item) => (
          <img key={item.id} src={item.image_url} alt={item.subtype ?? item.category} />
        ))}
      </div>

      <div className="recommendation-items compact-items">
        {recommendation.items.map((item) => (
          <div key={item.id} className="recommendation-item">
            <div>
              <strong>{item.subtype ?? item.category}</strong>
              <span>
                {item.color} · {item.style} · {item.occasion}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="breakdown-grid">
        {breakdownEntries.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{Math.round(value)}</strong>
          </div>
        ))}
      </div>

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
    </article>
  );
}
