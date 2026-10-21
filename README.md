# Sunwise — Vitamin D exposure estimate

Sunwise is a single-page, weather-aware educational estimate of a potentially suitable outdoor exposure window. It combines a user's location, a simplified solar-elevation calculation, hourly UV and weather forecasts, skin type, and approximate exposed skin area. The result is not medical advice and should not be treated as a prescription or a guaranteed vitamin D dose.

## Project structure

- `backend/` — FastAPI API, Open-Meteo client, solar/weather calculation, structured logs, metrics, tracing, and pytest suite.
- `frontend/` — Next.js/React responsive calculator and Playwright end-to-end tests.
- `openAPI-specs.yaml` — API contract for the landing page, calculation, locations, health, and metrics endpoints. FastAPI also serves generated docs at `/docs` and `/openapi.json`.
- `Dockerfile.azure`, `Dockerfile.aws` — multi-stage images that build the static Next.js UI and run it through the FastAPI service.

## Run locally

Requirements: Python 3.12+ and Node.js 20+.

1. Start the API:

   ```sh
   cd backend
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements-dev.txt
   uvicorn app.main:app --reload --port 8000
   ```

2. In a second terminal, start the frontend:

   ```sh
   cd frontend
   npm install
   npm run dev
   ```

3. Open `http://localhost:3000`. The frontend's development mode calls the API at `http://localhost:8000`; set `NEXT_PUBLIC_API_URL` to override it. For a production static build served by FastAPI, leave it unset so requests use the same origin.

Device geolocation is available on localhost and HTTPS. If permission is declined, choose a city from the location selector instead.

Email signups require PostgreSQL. Set `DATABASE_URL` to a PostgreSQL connection URL ending in `/email_list` (the connecting role needs permission to create that database on first use), for example `postgresql+psycopg://<user>:<password>@localhost:5432/email_list`. The service creates the database and `email_list` table when the first signup is submitted.

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Serves the exported Next.js application in production. |
| `POST` | `/process` | Returns today's estimate and 24 hourly chart points. |
| `POST` | `/email_list` | Creates or updates a personalized daily-window email signup. |
| `GET` | `/successful_submission` | Displays confirmation with a return link and seven-second redirect. |
| `GET` | `/locations` | Returns bundled country/city options. |
| `GET` | `/health` | Liveness response: `{"status":"ok"}`. |
| `GET` | `/metrics` | Prometheus request and latency metrics. |
| `GET` | `/docs` | Interactive FastAPI API documentation. |
| `GET` | `/openapi.json` | Generated OpenAPI document. |

Example request:

```json
{
  "latitude": 37.9838,
  "longitude": 23.7275,
  "location_name": "Athens, Greece",
  "skin_type": "III",
  "clothing_density": "summer clothes"
}
```

The response includes the selected local date, a natural-language recommendation, a one-hour peak window, estimated minutes, 24 hourly exposure values, hourly UV index values, and a safety advisory. Invalid requests use HTTP 422; unavailable or unusable forecast data use HTTP 502. Responses include `request_id` and the matching `X-Request-ID` header.

### Standard user journeys

1. **Use the device location:** leave “Use my current location” selected, choose a skin type and clothing option, allow the browser location prompt, and request an estimate. The browser sends coordinates to the API, which retrieves the local Open-Meteo forecast and returns the chart and suggested hour.
2. **Choose a city manually:** select one of the bundled city options, choose skin and clothing details, and request an estimate. No browser location permission is needed.
3. **No suitable forecast / provider error:** the chart indicates when the simple model considers sunlight and weather suitable. If no hour qualifies, the response says so; provider failures and invalid selections are surfaced as readable messages with a request ID for support.
4. **Subscribe for daily windows:** enter a name and email on the landing page. The form uses the currently selected city or browser location and skin type; repeat signups update location, skin type, and timezone for the existing email. A confirmation page provides a return link and automatically redirects after seven seconds.

## Calculation and safety notes

- Open-Meteo supplies hourly UV index, cloud cover, precipitation probability, precipitation, rain, showers, snowfall, and weather code for the automatically resolved timezone.
- The calculation estimates solar elevation from latitude, longitude, local date/time, and UTC offset. It considers remaining hours with solar elevation of at least 25°, UV index of at least 1, cloud cover no greater than 85%, precipitation probability below 50%, and no material precipitation.
- A simplified skin-type baseline is adjusted for UV index, cloud cover, and approximate exposed-skin fractions (100%, 85%, 30%, and 5%) and capped at 30 minutes. These are product heuristics, not clinically validated values. Clouds do not eliminate UV exposure, and people can burn.
- The UI presents a safety advisory. Users should not stay out long enough to burn, should use suitable sun protection, and should speak with a healthcare professional about vitamin D needs.
- The city list is built from GeoNames `cities500` and `countryInfo` data (CC BY 4.0). It includes up to the three most populous GeoNames populated places per country; countries with fewer than three entries in the source may have fewer options. Source: [GeoNames](https://www.geonames.org/).

## Observability

Logs are JSON written to stdout and include a timestamp, level, message, request ID, and exception stack trace when applicable. Incoming request IDs are validated; otherwise, a UUID is generated and returned in `X-Request-ID`. OpenTelemetry instruments FastAPI and httpx so trace context is propagated to Open-Meteo. Prometheus instrumentation is exposed at `/metrics`.

## Tests

Backend tests enforce the configured 85% coverage target:

```sh
cd backend
pip install -r requirements-dev.txt
pytest
```

Frontend end-to-end tests:

```sh
cd frontend
npm install
npx playwright install chromium
npm run test:e2e
```

The GitHub Actions workflow runs backend coverage tests, builds the frontend, and runs the Playwright flows.

## Container images

Build either deployment variant from the repository root:

```sh
docker build -f Dockerfile.azure -t sunwise:azure .
docker build -f Dockerfile.aws -t sunwise:aws .
docker run --rm -p 8000:8000 sunwise:azure
```

Both images use multi-stage builds, a minimal Python runtime, a non-root user, and a health check. The app is served on port 8000.
