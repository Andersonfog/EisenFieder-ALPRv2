import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  apiCameras, apiSimilarVehicles, apiVehicles, downloadVehiclesCsv,
  openVehicleUpdates,
} from "../api";
import { Lightbox } from "../components/ImageViewer.jsx";
import {
  AuthImage, Card, DirectionBadge, Plate, TypeBadge, VEHICLE_TYPES,
  formatTime, pretty,
} from "../ui.jsx";

const EMPTY = {
  plate: "", company: "", vehicle_type: "", direction: "",
  is_commercial: "", flagged: "", camera_id: "",
};

// Fallback refresh only: the push channel (openVehicleUpdates) delivers real
// changes the instant they land, so polling is just a safety net.
const POLL_MS = 5000;

export default function Vehicles() {
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState(EMPTY);
  const [data, setData] = useState({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [live, setLive] = useState(true);          // auto-refresh on/off
  const [flash, setFlash] = useState(() => new Set()); // ids of just-arrived rows
  const knownIds = useRef(null);                   // ids in the last result

  // Swap in fresh results and briefly highlight rows we've never shown before.
  function applyData(d) {
    const prev = knownIds.current;
    if (prev) {
      const fresh = d.items.filter((v) => !prev.has(v.id)).map((v) => v.id);
      if (fresh.length) {
        setFlash((s) => new Set([...s, ...fresh]));
        setTimeout(() => {
          setFlash((s) => {
            const n = new Set(s);
            for (const id of fresh) n.delete(id);
            return n;
          });
        }, 2500);
      }
    }
    knownIds.current = new Set(d.items.map((v) => v.id));
    setData(d);
  }

  function load(f = filters) {
    setLoading(true);
    knownIds.current = null; // a new search shouldn't flash every row
    const params = { ...f, limit: 100 };
    apiVehicles(params)
      .then(applyData)
      .catch(() => setData({ total: 0, items: [] }))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    // Prefill filters from the URL (deep links from Insights, e.g. ?plate=RGL-1001).
    const initial = { ...EMPTY };
    for (const k of Object.keys(EMPTY)) {
      const v = searchParams.get(k);
      if (v) initial[k] = v;
    }
    setFilters(initial);
    load(initial);
    apiCameras().then(setCameras).catch(() => setCameras([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live mode: the backend PUSHES a ping the instant the log changes and we
  // re-fetch right away (silently — no loading flicker, errors keep old data).
  // A slow poll stays on as a safety net if the push stream ever drops.
  useEffect(() => {
    if (!live) return undefined;
    const refresh = () =>
      apiVehicles({ ...filters, limit: 100 }).then(applyData).catch(() => {});
    const t = setInterval(refresh, POLL_MS);
    let pending = null;
    const stop = openVehicleUpdates(() => {
      if (pending) return; // coalesce ping bursts into one fetch
      pending = setTimeout(() => {
        pending = null;
        refresh();
      }, 120);
    });
    return () => {
      clearInterval(t);
      stop();
      clearTimeout(pending);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, filters]);

  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="stencil text-sm text-gray-400">Vehicle Log</h1>
          <p className="mt-1 text-xs font-mono text-gray-600">
            {loading ? "processing..." : `${data.total} record${data.total === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setLive(!live)}
            title={live ? "Auto-refresh is ON — click to pause" : "Auto-refresh is PAUSED — click to resume"}
            className={`flex items-center gap-2 border px-3 py-2 text-xs font-mono uppercase transition ${
              live
                ? "border-red-500/60 bg-gray-950 text-red-400"
                : "border-gray-600 bg-gray-950 text-gray-500 hover:border-amber-400 hover:text-amber-300"
            }`}
          >
            <span className={`led ${live ? "led-red led-blink" : "led-amber"}`} />
            {live ? "LIVE" : "PAUSED"}
          </button>
          <button
            onClick={() => downloadVehiclesCsv(filters)}
            className="border border-gray-600 bg-gray-950 px-3 py-2 text-xs font-mono uppercase text-gray-300 hover:border-amber-400 hover:text-amber-300 transition"
          >
            CSV export
          </button>
        </div>
      </div>

      {/* Search bar */}
      <Card className="p-4 border-t-2 border-t-amber-400 space-y-3">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
          <input
            placeholder="PLATE"
            value={filters.plate}
            onChange={set("plate")}
            className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400 placeholder-gray-600"
          />
          <input
            placeholder="COMPANY"
            value={filters.company}
            onChange={set("company")}
            className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400 placeholder-gray-600"
          />
          <select
            value={filters.vehicle_type}
            onChange={set("vehicle_type")}
            className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400"
          >
            <option value="">ANY TYPE</option>
            {VEHICLE_TYPES.map((t) => (
              <option key={t} value={t}>{pretty(t).toUpperCase()}</option>
            ))}
          </select>
          <select
            value={filters.direction}
            onChange={set("direction")}
            className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400"
          >
            <option value="">ANY DIRECTION</option>
            <option value="in">IN</option>
            <option value="out">OUT</option>
          </select>
          <select
            value={filters.is_commercial}
            onChange={set("is_commercial")}
            className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400"
          >
            <option value="">ANY VEHICLE</option>
            <option value="true">COMMERCIAL</option>
            <option value="false">PRIVATE</option>
          </select>
          <select
            value={filters.flagged}
            onChange={set("flagged")}
            className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400"
          >
            <option value="">ANY STATUS</option>
            <option value="true">FLAGGED</option>
          </select>
          {cameras.length > 1 && (
            <select
              value={filters.camera_id}
              onChange={set("camera_id")}
              className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-amber-400 col-span-2 md:col-span-3 lg:col-span-1"
            >
              <option value="">ALL CAMERAS</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>{(c.name || c.id).toUpperCase()}</option>
              ))}
            </select>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => load()}
            className="border border-amber-500 bg-amber-400 px-3 py-1.5 text-xs font-mono font-bold uppercase tracking-widest text-black hover:bg-amber-300 transition"
          >
            SEARCH
          </button>
          <button
            onClick={() => {
              setFilters(EMPTY);
              load(EMPTY);
            }}
            className="border border-gray-700 bg-gray-950 px-3 py-1.5 text-xs font-mono uppercase text-gray-400 hover:border-amber-400 hover:text-amber-300 transition"
          >
            CLEAR
          </button>
        </div>
      </Card>

      {/* Results table */}
      <Card className="overflow-hidden border-t-2 border-t-amber-400">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-gray-950 text-gray-500 border-b border-gray-700">
            <tr>
              <th className="px-4 py-2 uppercase tracking-widest">Plate</th>
              <th className="px-4 py-2 uppercase tracking-widest">Type</th>
              <th className="px-4 py-2 uppercase tracking-widest">Color</th>
              <th className="px-4 py-2 uppercase tracking-widest">Occ</th>
              <th className="px-4 py-2 uppercase tracking-widest">Company</th>
              <th className="px-4 py-2 uppercase tracking-widest">Dir</th>
              <th className="px-4 py-2 uppercase tracking-widest">Captured</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((v) => (
              <tr
                key={v.id}
                onClick={() => setSelected(v)}
                className={`cursor-pointer border-t border-gray-800 hover:bg-gray-900 transition ${
                  v.flagged ? "border-l-4 border-l-amber-400 bg-amber-400/5" : ""
                } ${flash.has(v.id) ? "animate-pulse bg-amber-400/10" : ""}`}
              >
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <Plate text={v.plate_text} />
                    {v.pending && (
                      <span className="flex items-center gap-1 border border-amber-400/50 px-1 py-0.5 text-[9px] font-mono uppercase text-amber-300">
                        <span className="led led-amber led-blink" />
                        in view
                      </span>
                    )}
                    {v.visit && v.visit.count > 1 && (
                      <span
                        className="border border-gray-600 bg-gray-900 px-1 py-0.5 text-[9px] font-mono uppercase text-gray-300"
                        title={
                          v.visit.by === "appearance"
                            ? "Matched by appearance (side-profile) — a suggestion, not proof"
                            : "Same plate seen before"
                        }
                      >
                        ↻ visit #{v.visit.count}
                        {v.visit.by === "appearance" ? "?" : ""}
                      </span>
                    )}
                    {v.flagged && (
                      <span className="bg-amber-400 px-1 py-0.5 text-[9px] text-black font-mono font-bold uppercase">
                        ALERT {v.flag_reason || "watchlist"}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2"><TypeBadge type={v.vehicle_type} /></td>
                <td className="px-4 py-2 uppercase text-gray-400">{(v.vehicle_color || "–").slice(0, 8)}</td>
                <td className="px-4 py-2 text-gray-400">{v.occupant_count ?? "–"}</td>
                <td className="px-4 py-2 text-gray-400 truncate">{v.company_name || "–"}</td>
                <td className="px-4 py-2"><DirectionBadge direction={v.direction} /></td>
                <td className="px-4 py-2 text-gray-500 text-[10px]">{formatTime(v.captured_at).split(' ')[1] || "–"}</td>
                <td className="px-4 py-2 text-right text-gray-700">›</td>
              </tr>
            ))}
            {!loading && data.items.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-gray-600 font-mono">
                  — no records —
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      {selected && (
        <DetailModal
          vehicle={selected}
          onClose={() => setSelected(null)}
          onSwitch={setSelected}
        />
      )}
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="border border-gray-800 bg-gray-950/60 p-3">
      <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono">{label}</div>
      <div className="mt-1 text-xs text-gray-300 font-mono break-all">{value ?? "–"}</div>
    </div>
  );
}

function ZoomableThumb({ url, alt, label, onOpen }) {
  if (!url) return <AuthImage url={url} alt={alt} className="h-48 w-full border border-gray-800 object-cover bg-gray-900" />;
  return (
    <button
      onClick={() => onOpen({ url, caption: label })}
      className="group relative block h-48 w-full overflow-hidden border border-gray-800 bg-gray-950"
      title="Click to zoom"
    >
      <AuthImage url={url} alt={alt} className="h-full w-full object-cover" />
      <span className="absolute right-2 top-2 bg-black/90 px-2 py-1 text-[10px] text-gray-300 font-mono opacity-0 transition group-hover:opacity-100">
        ZOOM
      </span>
    </button>
  );
}

// Past sightings whose side-profile fingerprint looks like this vehicle's.
// Appearance only ("possibly the same car") — plates do identity.
function SimilarVehicles({ vehicle, onSwitch }) {
  const [items, setItems] = useState(null);

  useEffect(() => {
    let alive = true;
    setItems(null);
    apiSimilarVehicles(vehicle.id)
      .then((d) => alive && setItems(d.items || []))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [vehicle.id]);

  if (!items || items.length === 0) return null;
  return (
    <div className="mt-4 border-t border-gray-800 pt-4">
      <div className="mb-2 text-[9px] uppercase tracking-widest text-gray-600 font-mono">
        Looks like — side-profile match ({items.length})
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {items.map(({ score, event }) => (
          <button
            key={event.id}
            onClick={() => onSwitch && onSwitch(event)}
            className="group border border-gray-800 bg-gray-950 text-left transition hover:border-amber-400"
            title="Open this sighting"
          >
            <AuthImage
              url={event.profile_image_url || event.image_url}
              alt="similar vehicle"
              className="h-20 w-full object-cover"
            />
            <div className="flex items-center justify-between px-2 py-1">
              <span className="truncate font-mono text-[10px] text-gray-400">
                {event.plate_text || pretty(event.vehicle_type || "vehicle")}
              </span>
              <span className="ml-1 font-mono text-[10px] text-amber-300">
                {Math.round(score * 100)}%
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function DetailModal({ vehicle: v, onClose, onSwitch }) {
  const [zoom, setZoom] = useState(null);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <Card
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto p-6 border-t-4 border-t-amber-400"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between pb-4 border-b border-gray-800" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center gap-2">
            <Plate text={v.plate_text} />
            <TypeBadge type={v.vehicle_type} />
            <DirectionBadge direction={v.direction} />
            {v.pending && (
              <span className="flex items-center gap-1 border border-amber-400/50 px-1.5 py-0.5 text-[10px] font-mono uppercase text-amber-300">
                <span className="led led-amber led-blink" />
                still in view
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-gray-600 hover:text-white font-mono text-lg">×</button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 mb-4" onClick={(e) => e.stopPropagation()}>
          <ZoomableThumb
            url={v.image_url}
            alt="scene"
            label={`Scene · ${v.plate_text || v.vehicle_type || "vehicle"}`}
            onOpen={setZoom}
          />
          <ZoomableThumb
            url={v.plate_image_url}
            alt="plate"
            label={`Plate · ${v.plate_text || ""}`}
            onOpen={setZoom}
          />
          {v.profile_image_url && (
            <ZoomableThumb
              url={v.profile_image_url}
              alt="side profile"
              label={`Side profile · ${v.plate_text || v.vehicle_type || "vehicle"}`}
              onOpen={setZoom}
            />
          )}
        </div>

        {zoom && (
          <Lightbox url={zoom.url} caption={zoom.caption} onClose={() => setZoom(null)} />
        )}

        {v.flagged && (
          <div className="mb-4 border border-amber-500 bg-amber-400 px-3 py-2 text-xs text-black font-mono font-bold uppercase">
            ⚠ ALERT: {v.flag_reason || "watchlisted plate"}
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Field label="Make" value={v.vehicle_make} />
          <Field label="Model" value={v.vehicle_model} />
          <Field label="Color" value={v.vehicle_color} />
          <Field label="Occupants" value={v.occupant_count} />
          <Field label="Company" value={v.company_name} />
          <Field label="Region" value={v.plate_region} />
          <Field
            label="Plate conf"
            value={v.plate_confidence != null ? `${Math.round(v.plate_confidence * 100)}%` : "–"}
          />
          <Field label="Camera" value={v.camera_id} />
          <Field label="Detected" value={formatTime(v.captured_at)} />
          <Field
            label="Det conf"
            value={`${Math.round((v.confidence || 0) * 100)}%`}
          />
          {v.visit && v.visit.count > 1 && (
            <Field
              label={v.visit.by === "appearance" ? "Visits (by look)" : "Visits"}
              value={`#${v.visit.count} — first seen ${formatTime(v.visit.first_seen)}`}
            />
          )}
        </div>

        <SimilarVehicles vehicle={v} onSwitch={onSwitch} />
      </Card>
    </div>
  );
}
