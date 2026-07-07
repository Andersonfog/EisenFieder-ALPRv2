import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiCameraLiveStatus, apiCameras, apiStats, apiVehicles } from "../api";
import { profileById } from "../alprProfiles";
import { Card, DirectionBadge, Plate, TypeBadge, timeAgo } from "../ui.jsx";

function Stat({ label, value, alert }) {
  const hot = alert && value > 0;
  return (
    <Card className={`p-5 ${hot ? "bg-amber-400/10" : ""}`}>
      <div className={`metric-value ${hot ? "text-amber-300" : ""}`}>{value}</div>
      <div className="metric-label">{label}</div>
    </Card>
  );
}

function Mini({ label, value, hot }) {
  return (
    <div className="rounded-md border border-gray-800 bg-gray-950/50 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 truncate text-sm ${hot ? "font-semibold text-amber-300" : "text-gray-200"}`}>
        {value}
      </div>
    </div>
  );
}

export default function Overview() {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [cameras, setCameras] = useState([]);
  const [liveStatus, setLiveStatus] = useState({});
  const [error, setError] = useState("");

  useEffect(() => {
    apiStats().then(setStats).catch((e) => setError(e.message));
    apiVehicles({ limit: 6 }).then((r) => setRecent(r.items)).catch(() => {});
    apiCameras()
      .then(async (list) => {
        setCameras(list);
        const entries = await Promise.all(
          list.map((camera) =>
            apiCameraLiveStatus(camera.id)
              .then((status) => [camera.id, status])
              .catch(() => [camera.id, { online: false }]),
          ),
        );
        setLiveStatus(Object.fromEntries(entries));
      })
      .catch(() => setCameras([]));
  }, []);

  if (error) {
    return <div className="app-page text-sm text-red-300">Error: {error}</div>;
  }
  if (!stats) {
    return <div className="app-page text-sm text-gray-500">Initializing...</div>;
  }

  const maxType = Math.max(1, ...stats.by_type.map((t) => t.count));

  return (
    <div className="app-page space-y-6">
      <div>
        <p className="page-kicker">Overview</p>
        <h1 className="page-title">ALPR operations</h1>
        <p className="page-copy">Camera health, recent reads, and traffic mix at a glance.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Plate reads" value={stats.total_vehicles} />
        <Stat label="Last 24h" value={stats.vehicles_last_24h} />
        <Stat label="Watch hits" value={stats.flagged_total} alert />
        <Stat label="Fleet reads" value={stats.commercial_total} />
        <Stat label="Cameras" value={stats.total_cameras} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">Camera readiness</h2>
            <Link to="/live" className="text-sm text-amber-300 hover:text-amber-200">
              Open live monitor
            </Link>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {cameras.map((camera) => {
              const status = liveStatus[camera.id] || {};
              const profile = profileById(status.profile || camera.settings?.quality_profile);
              return (
                <div key={camera.id} className="rounded-md border border-gray-800 bg-gray-950/45 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-gray-100">{camera.name || camera.id}</div>
                      <div className="mt-1 truncate text-sm text-gray-500">{camera.location || camera.id}</div>
                    </div>
                    <span
                      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs ${
                        status.online ? "border-red-400/50 text-red-300" : "border-gray-700 text-gray-500"
                      }`}
                    >
                      <span className={`led ${status.online ? "led-red led-blink" : ""}`} />
                      {status.online ? "Live" : "Idle"}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-2">
                    <Mini label="Profile" value={profile.short} hot />
                    <Mini
                      label="Frame"
                      value={
                        status.frame_width && status.frame_height
                          ? `${status.frame_width}x${status.frame_height}`
                          : profile.resolution
                      }
                    />
                    <Mini label="Detect" value={status.detect_fps ? `${status.detect_fps} fps` : "-"} />
                  </div>
                </div>
              );
            })}
            {cameras.length === 0 && <div className="muted-empty">No cameras registered.</div>}
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="section-title">Vehicle distribution</h2>
          {stats.by_type.length === 0 && <div className="mt-4 muted-empty">No data yet.</div>}
          <div className="mt-4 space-y-3">
            {stats.by_type.map((t) => (
              <div key={t.label} className="flex items-center gap-3">
                <div className="w-20 text-sm text-gray-400">{t.label}</div>
                <div className="h-2 flex-1 rounded-full bg-gray-950">
                  <div
                    className="h-full rounded-full bg-amber-400"
                    style={{ width: `${(t.count / maxType) * 100}%` }}
                  />
                </div>
                <div className="w-10 text-right text-sm text-gray-300">{t.count}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card className="table-shell">
        <div className="flex items-center justify-between border-b border-gray-800 px-5 py-4">
          <h2 className="section-title">Recent reads</h2>
          <Link to="/vehicles" className="text-sm text-amber-300 hover:text-amber-200">
            Review log
          </Link>
        </div>
        <div className="divide-y divide-gray-800">
          {recent.length === 0 && <div className="p-5 muted-empty">No events yet.</div>}
          {recent.map((v) => (
            <div
              key={v.id}
              className={`grid gap-3 px-5 py-4 lg:grid-cols-[1fr_auto] ${
                v.flagged ? "bg-amber-400/10" : ""
              }`}
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Plate text={v.plate_text} />
                <TypeBadge type={v.vehicle_type} />
                {v.flagged && (
                  <span className="rounded-md bg-amber-400 px-2 py-0.5 text-xs font-semibold text-gray-950">
                    Alert
                  </span>
                )}
                {v.company_name && <span className="truncate text-sm text-gray-400">{v.company_name}</span>}
              </div>
              <div className="flex items-center gap-3 whitespace-nowrap">
                <DirectionBadge direction={v.direction} />
                <span className="text-sm text-gray-500">{timeAgo(v.captured_at)}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
