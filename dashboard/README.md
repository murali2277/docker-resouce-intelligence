# DRI Dashboard

React + Vite + TypeScript single-page app for the Docker Resource Intelligence agent.

## Prerequisites

- Node.js v18+ and npm v9+
- A running DRI agent (default: `http://localhost:8000`)

## Running locally

```bash
# From the repo root:
cd dashboard
npm install
npm run dev
```

The dev server starts at **http://localhost:5173** and proxies nothing — all
`/api/v1/*` requests go directly to `http://localhost:8000` (the DRI agent).

If the agent runs on a different host/port, or requires API key authentication, set the environment variables before starting:

```bash
VITE_API_BASE=http://192.168.1.10:8000 VITE_API_KEY=your-api-key npm run dev
```

## Building for production

```bash
VITE_API_BASE=http://192.168.1.10:8000 VITE_API_KEY=your-api-key npm run build
# Output: dashboard/dist/
```

Serve `dist/` with any static file server (nginx, `npx serve dist`, etc.).
Point `VITE_API_BASE` (and optionally `VITE_API_KEY`) to the DRI agent's configuration at build time.

## Views

| URL | Source | Data source |
|-----|--------|-------------|
| `/` | Overview.tsx | `GET /api/v1/metrics` + `GET /api/v1/health` — polls every 10s |
| `/alerts` | Alerts.tsx | `GET /api/v1/alerts` — polls every 10s, sortable by column |
| `/recommendations` | Recommendations.tsx | `GET /api/v1/recommendations` — polls every 60s |
| `/forecast` | Forecast.tsx | `GET /api/v1/forecast/{id}` — on-demand |
| `/actions` | ActionsHistory.tsx | `GET /api/v1/actions/history` — polls every 15s |

Clicking any container card on the Overview page opens a detail modal with:
- 60-minute moving-average trend charts (CPU + memory, via recharts)
- The container's cached recommendation (filtered client-side by `container_id`)
- A 24h memory forecast

## API field names

`dashboard/src/api/client.ts` mirrors every field from `src/dri/api/models.py`
**exactly as named** — no renaming. If the backend adds or renames a field,
update `client.ts` first.

## Note on Docker deployment

The recommended production deployment path is using `docker-compose` as described in the root `README.md`. 
The `npm run dev` approach is kept as a local-dev alternative.

### VITE_API_BASE Limitation
Note that the `VITE_API_BASE` variable is baked in at build time. This means if you build the Docker image, the API URL is statically injected into the minified Javascript. This won't work well for deployments where the agent's public URL isn't known at image-build time. 

*(Nice-to-have: A future improvement could introduce an `envsubst` step in the nginx entrypoint to dynamically inject `VITE_API_BASE` at container start instead of build time.)*
