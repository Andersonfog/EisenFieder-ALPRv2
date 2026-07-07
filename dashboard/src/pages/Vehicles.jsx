import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  apiCameras,
  apiSimilarVehicles,
  apiVehicles,
  downloadVehiclesCsv,
  openVehicleUpdates,
} from "../api";
import { Lightbox } from "../components/ImageViewer.jsx";
import {
  AuthImage,
  Card,
  DirectionBadge,
  Plate,
  TypeBadge,
  VEHICLE_TYPES,
  formatTime,
  pretty,
} from "../ui.jsx";

const EMPTY = {
  plate: "",
  company: "",
  vehicle_type: "",
  direction: "",
  is_commercial: "",
  flagged: "",
  camera_id: "",
};

const POLL_MS = 5000;

export default function Vehicles() {
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState(EMPTY);
  const [data, setData] = useState({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [live, setLive] = useState(true);
  const [flash, setFlash] = useState(() => new Set());
  const knownIds = useRef(null);

  function applyData(next) {
    const prev = knownIds.current;
    if (prev) {
      const fresh = next.items.filter((vehicle) => !prev.has(vehicle.id)).map((vehicle) => vehicle.id);
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
    knownIds.current = new Set(next.items.map((vehicle) => vehicle.id));
    setData(next);
  }

  function load(f = filters) {
    setLoading(true);
    knownIds.current = null;
    apiVehicles({ ...f, limit: 100 })
      .then(applyData)
      .catch(() => setData({ total: 0, items: [] }))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    const initial = { ...EMPTY };
    for (const key of Object.keys(EMPTY)) {
      const value = searchParams.get(key);
      if (value) initial[key] = value;
    }
    setFilters(initial);
    load(initial);
    apiCameras().then(setCameras).catch(() => setCameras([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!live) return undefined;
    const refresh = () => apiVehicles({ ...filters, limit: 100 }).then(applyData).catch(() => {});
    const interval = setInterval(refresh, POLL_MS);
    let pending = null;
    const stop = openVehicleUpdates(() => {
      if (pending) return;
      pending = setTimeout(() => {
        pending = null;
        refresh();
      }, 120);
    });
    return () => {
      clearInterval(interval);
      stop();
      clearTimeout(pending);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, filters]);

  const set = (key) => (e) => setFilters({ ...filters, [key]: e.target.value });

  return (
    <div className="app-page space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="page-kicker">Plate log</p>
          <h1 className="page-title">Vehicle reads</h1>
          <p className="page-copy">
            {loading ? "Processing..." : `${data.total} record${data.total === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setLive(!live)}
            title={live ? "Auto-refresh is on. Click to pause." : "Auto-refresh is paused. Click to resume."}
            className={`btn-secondary ${live ? "border-red-400/50 text-red-300" : ""}`}
          >
            <span className={`led ${live ? "led-red led-blink" : "led-amber"}`} />
            {live ? "Live" : "Paused"}
          </button>
          <button onClick={() => downloadVehiclesCsv(filters)} className="btn-secondary">
            Export CSV
          </button>
        </div>
      </div>

      <Card className="p-5">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-7">
          <input placeholder="Plate" value={filters.plate} onChange={set("plate")} className="input-control" />
          <input placeholder="Company" value={filters.company} onChange={set("company")} className="input-control" />
          <select value={filters.vehicle_type} onChange={set("vehicle_type")} className="input-control">
            <option value="">Any type</option>
            {VEHICLE_TYPES.map((type) => (
              <option key={type} value={type}>
                {pretty(type)}
              </option>
            ))}
          </select>
          <select value={filters.direction} onChange={set("direction")} className="input-control">
            <option value="">Any direction</option>
            <option value="in">In</option>
            <option value="out">Out</option>
          </select>
          <select value={filters.is_commercial} onChange={set("is_commercial")} className="input-control">
            <option value="">Any vehicle</option>
            <option value="true">Commercial</option>
            <option value="false">Private</option>
          </select>
          <select value={filters.flagged} onChange={set("flagged")} className="input-control">
            <option value="">Any status</option>
            <option value="true">Flagged</option>
          </select>
          {cameras.length > 1 && (
            <select value={filters.camera_id} onChange={set("camera_id")} className="input-control">
              <option value="">All cameras</option>
              {cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.name || camera.id}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="mt-4 flex gap-2">
          <button onClick={() => load()} className="btn-primary">
            Search
          </button>
          <button
            onClick={() => {
              setFilters(EMPTY);
              load(EMPTY);
            }}
            className="btn-secondary"
          >
            Clear
          </button>
        </div>
      </Card>

      <Card className="table-shell">
        <table className="data-table">
          <thead>
            <tr>
              <th>Plate</th>
              <th>Type</th>
              <th>Color</th>
              <th>Occ</th>
              <th>Company</th>
              <th>Dir</th>
              <th>Captured</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((vehicle) => (
              <tr
                key={vehicle.id}
                onClick={() => setSelected(vehicle)}
                className={`cursor-pointer ${vehicle.flagged ? "bg-amber-400/5" : ""} ${
                  flash.has(vehicle.id) ? "animate-pulse bg-amber-400/10" : ""
                }`}
              >
                <td>
                  <div className="flex flex-wrap items-center gap-2">
                    <Plate text={vehicle.plate_text} />
                    {vehicle.pending && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/40 px-2 py-0.5 text-xs text-amber-300">
                        <span className="led led-amber led-blink" />
                        In view
                      </span>
                    )}
                    {vehicle.visit && vehicle.visit.count > 1 && (
                      <span
                        className="rounded-md border border-gray-700 bg-gray-950 px-2 py-0.5 text-xs text-gray-300"
                        title={
                          vehicle.visit.by === "appearance"
                            ? "Matched by appearance. Treat as a suggestion, not proof."
                            : "Same plate seen before"
                        }
                      >
                        Visit #{vehicle.visit.count}
                        {vehicle.visit.by === "appearance" ? "?" : ""}
                      </span>
                    )}
                    {vehicle.flagged && (
                      <span className="rounded-md bg-amber-400 px-2 py-0.5 text-xs font-semibold text-gray-950">
                        Alert {vehicle.flag_reason || "watchlist"}
                      </span>
                    )}
                  </div>
                </td>
                <td>
                  <TypeBadge type={vehicle.vehicle_type} />
                </td>
                <td className="text-gray-400">{(vehicle.vehicle_color || "-").slice(0, 12)}</td>
                <td className="text-gray-400">{vehicle.occupant_count ?? "-"}</td>
                <td className="max-w-52 truncate text-gray-400">{vehicle.company_name || "-"}</td>
                <td>
                  <DirectionBadge direction={vehicle.direction} />
                </td>
                <td className="whitespace-nowrap text-gray-500">{formatTime(vehicle.captured_at).split(" ")[1] || "-"}</td>
                <td className="text-right text-gray-600">Open</td>
              </tr>
            ))}
            {!loading && data.items.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center text-gray-500">
                  No records.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      {selected && <DetailModal vehicle={selected} onClose={() => setSelected(null)} onSwitch={setSelected} />}
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="rounded-md border border-gray-800 bg-gray-950/50 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 break-all text-sm text-gray-300">{value ?? "-"}</div>
    </div>
  );
}

function ZoomableThumb({ url, alt, label, onOpen }) {
  if (!url) {
    return <AuthImage url={url} alt={alt} className="h-48 w-full rounded-md border border-gray-800 bg-gray-900 object-cover" />;
  }
  return (
    <button
      onClick={() => onOpen({ url, caption: label })}
      className="group relative block h-48 w-full overflow-hidden rounded-md border border-gray-800 bg-gray-950"
      title="Click to zoom"
    >
      <AuthImage url={url} alt={alt} className="h-full w-full object-cover" />
      <span className="absolute right-2 top-2 rounded-md bg-black/80 px-2 py-1 text-xs text-gray-300 opacity-0 transition group-hover:opacity-100">
        Zoom
      </span>
    </button>
  );
}

function SimilarVehicles({ vehicle, onSwitch }) {
  const [items, setItems] = useState(null);

  useEffect(() => {
    let alive = true;
    setItems(null);
    apiSimilarVehicles(vehicle.id)
      .then((data) => alive && setItems(data.items || []))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [vehicle.id]);

  if (!items || items.length === 0) return null;
  return (
    <div className="mt-5 border-t border-gray-800 pt-5">
      <div className="mb-3 text-sm font-semibold text-gray-300">Similar side-profile matches ({items.length})</div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {items.map(({ score, event }) => (
          <button
            key={event.id}
            onClick={() => onSwitch && onSwitch(event)}
            className="group overflow-hidden rounded-md border border-gray-800 bg-gray-950 text-left transition hover:border-gray-600"
            title="Open this sighting"
          >
            <AuthImage
              url={event.profile_image_url || event.image_url}
              alt="similar vehicle"
              className="h-20 w-full object-cover"
            />
            <div className="flex items-center justify-between px-2 py-2">
              <span className="truncate text-xs text-gray-400">{event.plate_text || pretty(event.vehicle_type || "vehicle")}</span>
              <span className="ml-2 text-xs text-amber-300">{Math.round(score * 100)}%</span>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4" onClick={onClose}>
      <Card className="max-h-[90vh] w-full max-w-3xl overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-4 border-b border-gray-800 pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <Plate text={v.plate_text} />
            <TypeBadge type={v.vehicle_type} />
            <DirectionBadge direction={v.direction} />
            {v.pending && (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/40 px-2 py-0.5 text-xs text-amber-300">
                <span className="led led-amber led-blink" />
                Still in view
              </span>
            )}
          </div>
          <button onClick={onClose} className="btn-secondary px-3 py-1.5">
            Close
          </button>
        </div>

        <div className="mb-5 grid gap-3 sm:grid-cols-2">
          <ZoomableThumb
            url={v.image_url}
            alt="scene"
            label={`Scene - ${v.plate_text || v.vehicle_type || "vehicle"}`}
            onOpen={setZoom}
          />
          <ZoomableThumb
            url={v.plate_image_url}
            alt="plate"
            label={`Plate - ${v.plate_text || ""}`}
            onOpen={setZoom}
          />
          {v.profile_image_url && (
            <ZoomableThumb
              url={v.profile_image_url}
              alt="side profile"
              label={`Side profile - ${v.plate_text || v.vehicle_type || "vehicle"}`}
              onOpen={setZoom}
            />
          )}
        </div>

        {zoom && <Lightbox url={zoom.url} caption={zoom.caption} onClose={() => setZoom(null)} />}

        {v.flagged && (
          <div className="mb-5 rounded-md border border-amber-400/50 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">
            Alert: {v.flag_reason || "watchlisted plate"}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Field label="Make" value={v.vehicle_make} />
          <Field label="Model" value={v.vehicle_model} />
          <Field label="Color" value={v.vehicle_color} />
          <Field label="Occupants" value={v.occupant_count} />
          <Field label="Company" value={v.company_name} />
          <Field label="Region" value={v.plate_region} />
          <Field label="Plate conf" value={v.plate_confidence != null ? `${Math.round(v.plate_confidence * 100)}%` : "-"} />
          <Field label="Camera" value={v.camera_id} />
          <Field label="Detected" value={formatTime(v.captured_at)} />
          <Field label="Det conf" value={`${Math.round((v.confidence || 0) * 100)}%`} />
          {v.visit && v.visit.count > 1 && (
            <Field
              label={v.visit.by === "appearance" ? "Visits by look" : "Visits"}
              value={`#${v.visit.count} - first seen ${formatTime(v.visit.first_seen)}`}
            />
          )}
        </div>

        <SimilarVehicles vehicle={v} onSwitch={onSwitch} />
      </Card>
    </div>
  );
}
