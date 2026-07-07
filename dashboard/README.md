# EisenFieder Surveillance — owner console

React 18 + Vite + Tailwind v4. The private web app where the business owner logs
in and reviews everything the entrance cameras captured.

## Run

```powershell
npm install
npm run dev          # http://127.0.0.1:5174
```

Point it at your backend with `VITE_API_BASE` (see `.env.example`); it defaults
to `http://127.0.0.1:8000`. Start the backend first (see `../backend`), then log
in with your owner account.

## Pages

| Page | What it does |
|---|---|
| **Overview** | Totals (vehicles, last 24h, flagged, commercial, cameras), a by-type bar chart, and the latest vehicles. |
| **Vehicle Log** | The searchable history — filter by plate (partial), company, type, direction, commercial, or flagged. Click a row for the full detail + stills. Export CSV. |
| **Watchlist** | Add/pause/remove plates to flag on sight. |
| **Cameras** | Register a camera (get its one-time pairing token + `.env` snippet), edit per-camera settings, regenerate tokens, remove. |

## Owner-only images

Captured stills are served behind the login. A plain `<img src>` can't load them
(it wouldn't send the token), so `ui.jsx`'s `AuthImage` fetches the bytes *with*
the bearer token and renders them from an object URL. CSV export works the same
way. This keeps footage private to the owner — there is no public image URL.

## Files

```
src/
  api.js               fetch client (+ authed media/CSV helpers)
  auth.jsx             login/session context
  ui.jsx               badges, formatters, AuthImage
  App.jsx              routes (protected)
  components/Layout.jsx sidebar shell
  pages/               Login, Overview, Vehicles, Watchlist, Cameras
```
