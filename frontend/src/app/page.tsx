"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type City = {
  name: string;
  latitude: number;
  longitude: number;
  population: number;
};

type Country = {
  country_code: string;
  country_name: string;
  cities: City[];
};

type Estimate = {
  location: string;
  date: string;
  recommendation: string;
  window_start: string | null;
  window_end: string | null;
  recommended_minutes: number;
  hourly_exposure_minutes: number[];
  hourly_uv_index: number[];
  advisory: string;
};

type Coordinates = Pick<City, "latitude" | "longitude"> & { name: string };

function apiBase() {
  if (process.env.NEXT_PUBLIC_API_URL !== undefined) return process.env.NEXT_PUBLIC_API_URL;
  return typeof window !== "undefined" && window.location.port === "3000" ? "http://localhost:8000" : "";
}
const SKIN_TYPES = [
  ["I", "I · Very fair"],
  ["II", "II · Fair"],
  ["III", "III · Medium"],
  ["IV", "IV · Olive"],
  ["V", "V · Deep brown"],
];
const CLOTHING_OPTIONS = [
  ["naked", "Naked · 100% skin exposed"],
  ["swimsuit", "Swimsuit · 85% skin exposed"],
  ["summer clothes", "Summer clothes · 30% skin exposed"],
  ["winter clothes", "Winter clothes · 5% skin exposed"],
];

export default function Home() {
  const [countries, setCountries] = useState<Country[]>([]);
  const [location, setLocation] = useState("auto");
  const [skinType, setSkinType] = useState("III");
  const [clothing, setClothing] = useState("summer clothes");
  const [deviceCoordinates, setDeviceCoordinates] = useState<Coordinates | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(true);

  useEffect(() => {
    let active = true;
    fetch(`${apiBase()}/locations`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Location choices could not be loaded. Please refresh and try again.");
        return (await response.json()) as Country[];
      })
      .then((data) => {
        if (active) setCountries(data);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Location choices could not be loaded.");
      })
      .finally(() => {
        if (active) setLoadingLocations(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedCity = useMemo(() => {
    if (location === "auto") return null;
    const [countryCode, cityIndex] = location.split(":");
    return countries.find((country) => country.country_code === countryCode)?.cities[Number(cityIndex)] ?? null;
  }, [countries, location]);

  async function getCoordinates(): Promise<Coordinates> {
    if (location !== "auto" && selectedCity) {
      const country = countries.find((item) => item.cities.includes(selectedCity));
      return {
        ...selectedCity,
        name: country ? `${selectedCity.name}, ${country.country_name}` : selectedCity.name,
      };
    }
    if (deviceCoordinates) return deviceCoordinates;
    if (!navigator.geolocation) {
      throw new Error("This browser cannot share your location. Choose a city from the list instead.");
    }
    const position = await new Promise<GeolocationPosition>((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(
        resolve,
        () => reject(new Error("We could not access your location. Allow location access or choose a city instead.")),
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
      );
    });
    const found = {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      name: "Your current location",
    };
    setDeviceCoordinates(found);
    return found;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setEstimate(null);
    try {
      const coordinates = await getCoordinates();
      const response = await fetch(`${apiBase()}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: coordinates.latitude,
          longitude: coordinates.longitude,
          location_name: coordinates.name,
          skin_type: skinType,
          clothing_density: clothing,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "We could not prepare your estimate. Please try again.");
      setEstimate(data as Estimate);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "We could not prepare your estimate. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Sunwise home">
          <span className="brand-mark" aria-hidden="true">☀</span>
          <span>sunwise</span>
        </a>
        <span className="top-note"><span className="status-dot" /> A little more daylight, thoughtfully</span>
      </header>

      <section className="intro">
        <p className="eyebrow">YOUR DAILY SUNSHINE CHECK-IN</p>
        <h1>Find your sun-safe<br /><span>moment.</span></h1>
        <p className="intro-copy">A simple, weather-aware estimate for today's potential vitamin D exposure window.</p>
      </section>

      <section className="calculator" aria-label="Sun exposure calculator">
        <aside className="controls-panel">
          <div className="panel-heading">
            <span className="step-number">01</span>
            <div>
              <h2>Your details</h2>
              <p>Personalize today's estimate</p>
            </div>
          </div>
          <form onSubmit={handleSubmit}>
            <label htmlFor="location">Where are you?</label>
            <select
              id="location"
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              disabled={loadingLocations}
            >
              <option value="auto">◎ Use my current location</option>
              {countries.map((country) => (
                <optgroup key={country.country_code} label={country.country_name}>
                  {country.cities.map((city, index) => (
                    <option key={`${country.country_code}-${city.name}-${index}`} value={`${country.country_code}:${index}`}>
                      {city.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <p className="field-hint">Your location is only used to get today's local forecast.</p>

            <label htmlFor="skin">Skin type</label>
            <select id="skin" value={skinType} onChange={(event) => setSkinType(event.target.value)}>
              {SKIN_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <p className="field-hint">Choose the option closest to your natural skin tone.</p>

            <label htmlFor="clothing">What will you wear?</label>
            <select id="clothing" value={clothing} onChange={(event) => setClothing(event.target.value)}>
              {CLOTHING_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>

            {error && <p className="error-message" role="alert">{error}</p>}
            <button className="submit-button" type="submit" disabled={loading || loadingLocations}>
              {loading ? <><span className="spinner" /> Checking your forecast…</> : <>Get my sun window <span aria-hidden="true">→</span></>}
            </button>
          </form>
          <p className="privacy-note"><span aria-hidden="true">⌖</span> Your coordinates are sent securely for this estimate only.</p>
        </aside>

        <section className="results-panel" aria-live="polite">
          <div className="panel-heading result-heading">
            <span className="step-number">02</span>
            <div>
              <h2>Your sunshine outlook</h2>
              <p>{estimate ? `${estimate.location} · ${new Date(`${estimate.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}` : "Your hourly exposure guide will appear here"}</p>
            </div>
          </div>

          <div className="chart-card">
            <div className="chart-title">
              <div><h3>Today's exposure guide</h3><p>Estimated minutes by local hour</p></div>
              <span className="chart-unit">MIN</span>
            </div>
            <ExposureChart values={estimate?.hourly_exposure_minutes ?? Array(24).fill(0)} />
          </div>

          <div className={`recommendation-card ${estimate ? "has-result" : ""}`}>
            <span className="sun-icon" aria-hidden="true">☀</span>
            <div>
              <p className="recommendation-label">{estimate ? "YOUR SUGGESTED WINDOW" : "READY WHEN YOU ARE"}</p>
              <p className="recommendation-text">
                {estimate?.recommendation ?? "Choose your details and we'll find the brightest suitable hour for you."}
              </p>
              {estimate && <p className="advisory">{estimate.advisory}</p>}
            </div>
          </div>
          <p className="data-note">Forecast and UV data provided by Open-Meteo · Times shown in your local timezone</p>
        </section>
      </section>

      <footer className="footer">
        <span>Made for brighter, more informed days.</span>
        <span className="disclaimer">An educational estimate only · Never stay in the sun long enough to burn</span>
      </footer>
    </main>
  );
}

function ExposureChart({ values }: { values: number[] }) {
  const max = Math.max(5, ...values);
  return (
    <div className="chart" role="img" aria-label={`Hourly recommended exposure minutes: ${values.join(", ")}`}>
      <div className="bar-area">
        {values.map((value, hour) => (
          <div className="bar-column" key={hour} title={`${hour.toString().padStart(2, "0")}:00 — ${value} minutes`}>
            <span className="bar-value">{value > 0 ? value : ""}</span>
            <span
              className={`bar ${value > 0 ? "active" : ""}`}
              style={{ height: `${value > 0 ? Math.max(10, (value / max) * 100) : 3}%` }}
            />
            <span className="bar-label">{hour % 3 === 0 ? hour.toString().padStart(2, "0") : ""}</span>
          </div>
        ))}
      </div>
      <div className="chart-axis"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span></div>
    </div>
  );
}
