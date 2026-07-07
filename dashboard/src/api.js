// Thin API client for the EisenFieder Surveillance backend.

export const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const TOKEN_KEY = "efs_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

function authHeaders() {
  const tok = getToken();
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, auth = true, isForm = false } = {}) {
  const headers = {};
  if (auth) Object.assign(headers, authHeaders());
  let payload = body;
  if (body && !isForm) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return null;
  return res.json();
}

function qs(params) {
  const clean = {};
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") clean[k] = v;
  });
  return new URLSearchParams(clean).toString();
}

// --- Auth ---
export const apiLogin = (email, password) =>
  request("/api/v1/auth/login", { method: "POST", body: { email, password }, auth: false });
export const apiMe = () => request("/api/v1/auth/me");

// --- Settings ---
export const apiSettings = () => request("/api/v1/settings");
export const apiUpdateSettings = (body) =>
  request("/api/v1/settings", { method: "PUT", body });

// --- Stats / vehicles ---
export const apiStats = () => request("/api/v1/stats");
export const apiAnalytics = (days = 30) => request(`/api/v1/analytics?days=${days}`);
export const apiVehicles = (params) => request(`/api/v1/vehicles?${qs(params)}`);
export const apiVehicle = (id) => request(`/api/v1/vehicles/${id}`);
// Past sightings that LOOK like this one (side-profile appearance match).
export const apiSimilarVehicles = (id) => request(`/api/v1/vehicles/${id}/similar`);

// --- Vehicle-log push channel ------------------------------------------------
// The backend sends a server-sent-events ping every time the log changes.
// EventSource can't carry the owner's bearer token, so we stream it via fetch
// (same trick as the MJPEG live view). Calls onPing() per change; returns a
// stop() function. Reconnects on drop.
export function openVehicleUpdates(onPing) {
  let stopped = false;
  let abort = null;

  async function pump() {
    while (!stopped) {
      abort = new AbortController();
      try {
        const res = await fetch(`${API_BASE}/api/v1/vehicles/updates`, {
          headers: authHeaders(),
          signal: abort.signal,
        });
        if (!res.ok || !res.body) throw new Error(`updates ${res.status}`);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf("\n\n")) !== -1) {
            const chunk = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            if (chunk.startsWith("data:")) onPing();
          }
        }
      } catch {
        /* fall through and reconnect below */
      }
      if (!stopped) await new Promise((r) => setTimeout(r, 2000));
    }
  }

  pump();
  return () => {
    stopped = true;
    abort && abort.abort();
  };
}

// --- Cameras ---
export const apiCameras = () => request("/api/v1/cameras");
export const apiCamera = (id) => request(`/api/v1/cameras/${id}`);
export const apiRegisterCamera = (body) =>
  request("/api/v1/cameras", { method: "POST", body });
export const apiRegenerateToken = (id) =>
  request(`/api/v1/cameras/${id}/regenerate-token`, { method: "POST" });
export const apiUpdateCameraSettings = (id, settings) =>
  request(`/api/v1/cameras/${id}/settings`, { method: "PUT", body: settings });
export const apiDeleteCamera = (id) =>
  request(`/api/v1/cameras/${id}`, { method: "DELETE" });

// --- Live preview ---
export const apiCameraLiveStatus = (id) =>
  request(`/api/v1/cameras/${id}/live/status`);
// The live frame is owner-only (needs the token), so it's fetched as bytes like
// the stored stills. Cache-busted so each poll gets the newest frame.
export const fetchLiveFrameObjectUrl = (id) =>
  fetchMediaObjectUrl(`/api/v1/cameras/${id}/live?t=${Date.now()}`);

// --- Live preview (MJPEG stream) --------------------------------------------
// A plain <img src> can't carry the owner's bearer token, so the browser can't
// just point at the multipart/x-mixed-replace endpoint directly. Instead we
// fetch it (auth header allowed on fetch), read the body as it streams in,
// and split out each JPEG part ourselves.
const MJPEG_BOUNDARY = new TextEncoder().encode("--efsframe");
const CRLF_CRLF = new TextEncoder().encode("\r\n\r\n");

function indexOfBytes(buf, seq, from = 0) {
  outer: for (let i = from; i <= buf.length - seq.length; i++) {
    for (let j = 0; j < seq.length; j++) {
      if (buf[i + j] !== seq[j]) continue outer;
    }
    return i;
  }
  return -1;
}

// Opens the MJPEG stream for a camera and calls onFrame(Uint8Array) for each
// JPEG frame as it arrives. Returns a stop() function. Reconnects on drop
// (backend restart, camera going offline mid-stream, etc).
export function openLiveStream(camId, onFrame) {
  let stopped = false;
  let abort = null;

  async function pump() {
    while (!stopped) {
      abort = new AbortController();
      try {
        const res = await fetch(`${API_BASE}/api/v1/cameras/${camId}/live/stream`, {
          headers: authHeaders(),
          signal: abort.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        const reader = res.body.getReader();
        let buf = new Uint8Array(0);
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          const merged = new Uint8Array(buf.length + value.length);
          merged.set(buf, 0);
          merged.set(value, buf.length);
          buf = merged;
          for (;;) {
            const bIdx = indexOfBytes(buf, MJPEG_BOUNDARY);
            if (bIdx === -1) break;
            const headerStart = bIdx + MJPEG_BOUNDARY.length;
            const headerEnd = indexOfBytes(buf, CRLF_CRLF, headerStart);
            if (headerEnd === -1) break; // wait for the rest of the header
            const headerText = new TextDecoder("latin1").decode(
              buf.slice(headerStart, headerEnd)
            );
            const m = /Content-Length:\s*(\d+)/i.exec(headerText);
            if (!m) {
              buf = buf.slice(headerEnd + 4);
              continue;
            }
            const bodyStart = headerEnd + 4;
            const bodyEnd = bodyStart + parseInt(m[1], 10);
            if (buf.length < bodyEnd) break; // wait for the rest of the frame
            onFrame(buf.slice(bodyStart, bodyEnd));
            buf = buf.slice(bodyEnd);
          }
        }
      } catch {
        /* fall through and reconnect below */
      }
      if (!stopped) await new Promise((r) => setTimeout(r, 1000));
    }
  }

  pump();
  return () => {
    stopped = true;
    abort && abort.abort();
  };
}

// --- Watchlist ---
export const apiWatchlist = () => request("/api/v1/watchlist");
export const apiAddWatch = (body) =>
  request("/api/v1/watchlist", { method: "POST", body });
export const apiToggleWatch = (id, active) =>
  request(`/api/v1/watchlist/${id}?active=${active}`, { method: "PATCH" });
export const apiDeleteWatch = (id) =>
  request(`/api/v1/watchlist/${id}`, { method: "DELETE" });

// --- Owner-only media -------------------------------------------------------
// Images are behind the login, so a plain <img src> can't load them (it won't
// send the token). We fetch the bytes WITH the token and hand back an object URL.
export async function fetchMediaObjectUrl(path) {
  if (!path) return null;
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError("media load failed", res.status);
  return URL.createObjectURL(await res.blob());
}

// CSV export (also behind the login): fetch with the token, trigger a download.
export async function downloadVehiclesCsv(params) {
  const res = await fetch(`${API_BASE}/api/v1/vehicles.csv?${qs(params)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new ApiError("export failed", res.status);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = "vehicles.csv";
  a.click();
  URL.revokeObjectURL(url);
}
