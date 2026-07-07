import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiCameraLiveStatus, apiCameras, apiStats, apiVehicles } from "../api";
import { profileById } from "../alprProfiles";
import { Card, DirectionBadge, Plate, TypeBadge, timeAgo } from "../ui.jsx";

function Stat({ label, value, alert }) {
  const hot = alert && value > 0;
  return (
    <Card className={`p-4 border-l-4 ${hot ? "border-l-amber-400" : "border-l-gray-500"}`}>
      <div className={`text-4xl font-bold font-mono ${hot ? "text-amber-300" : "text-gray-200"}`}>
        {value}
      </div>
      <div className="mt-2 text-[10px] uppercase tracking-widest font-mono text-gray-500">
        {label}
      </div>
    </Card>
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

  if (error)
    return (
      <div className="m-8 inline-block border border-red-400/60 bg-red-950/40 p-4 font-mono text-sm font-bold uppercase text-red-300">
        Error: {error}
      </div>
    );
  if (!stats) return <div className="p-8 text-gray-500 font-mono text-sm">initializing...</div>;

  const maxType = Math.max(1, ...stats.by_type.map((t) => t.count));

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="stencil text-sm text-gray-400 mb-4">ALPR System Status</h1>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Plate Reads" value={stats.total_vehicles} />
          <Stat label="Last 24h" value={stats.vehicles_last_24h} />
          <Stat label="Watch Hits" value={stats.flagged_total} alert />
          <Stat label="Fleet Reads" value={stats.commercial_total} />
          <Stat label="Cameras" value={stats.total_cameras} />
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="p-6 border-t-2 border-t-amber-400">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xs stencil text-gray-400">Camera Readiness</h2>
            <Link to="/live" className="text-xs text-amber-300 hover:text-amber-200 font-mono underline">
              command -&gt;
            </Link>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {cameras.map((camera) => {
              const status = liveStatus[camera.id] || {};
              const profile = profileById(status.profile || camera.settings?.quality_profile);
              return (
                <div key={camera.id} className="border border-gray-800 bg-gray-950/60 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-bold text-gray-200">
                        {camera.name || camera.id}
                      </div>
                      <div className="mt-1 truncate text-[10px] text-gray-600 font-mono">
                        {camera.location || camera.id}
                      </div>
                    </div>
                    <span
                      className={`border px-1.5 py-0.5 text-[10px] uppercase font-mono ${
                        status.online ? "border-red-400/60 text-red-300" : "border-gray-700 text-gray-500"
                      }`}
                    >
                      <span className={`led mr-1 ${status.online ? "led-red led-blink" : ""}`} />
                      {status.online ? "live" : "idle"}
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-1 text-[10px] font-mono">
                    <Mini label="profile" value={profile.short} hot />
                    <Mini
                      label="frame"
                      value={
                        status.frame_width && status.frame_height
                          ? `${status.frame_width}x${status.frame_height}`
                          : profile.resolution
                      }
                    />
                    <Mini label="detect" value={status.detect_fps ? `${status.detect_fps}fps` : "--"} />
                  </div>
                </div>
              );
            })}
            {cameras.length === 0 && (
              <div className="text-xs text-gray-600 font-mono">-- no cameras registered --</div>
            )}
          </div>
        </Card>

        <Card className="p-6 border-t-2 border-t-amber-400">
          <h2 className="mb-4 text-xs stencil text-gray-400">Vehicle Distribution</h2>
          {stats.by_type.length === 0 && (
            <div className="text-xs text-gray-600 font-mono">-- no data --</div>
          )}
          <div className="space-y-3">
            {stats.by_type.map((t) => (
              <div key={t.label} className="flex items-center gap-3">
                <div className="w-16 text-xs text-gray-500 font-mono uppercase">{t.label}</div>
                <div className="h-2 flex-1 bg-gray-950 border border-gray-700">
                  <div className="h-full bg-amber-400" style={{ width: `${(t.count / maxType) * 100}%` }} />
                </div>
                <div className="w-10 text-right text-xs text-gray-300 font-mono">{t.count}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card className="p-6 border-t-2 border-t-amber-400">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xs stencil text-gray-400">Recent Plate Reads</h2>
          <Link to="/vehicles" className="text-xs text-amber-300 hover:text-amber-200 font-mono underline">
            review -&gt;
          </Link>
        </div>
        <div className="grid gap-2 xl:grid-cols-2">
          {recent.length === 0 && <div className="text-gray-600 font-mono text-xs">-- no events --</div>}
          {recent.map((v) => (
            <div
              key={v.id}
              className={`flex items-center justify-between gap-2 border border-gray-800 bg-gray-950/60 px-3 py-2 ${
                v.flagged ? "border-l-4 border-l-amber-400 bg-amber-400/10" : ""
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <Plate text={v.plate_text} />
                <TypeBadge type={v.vehicle_type} />
                {v.flagged && (
                  <span className="bg-amber-400 px-1 py-0.5 text-[9px] text-black font-mono font-bold uppercase">
                    alert
                  </span>
                )}
                {v.company_name && (
                  <span className="text-gray-400 truncate font-mono">{v.company_name}</span>
                )}
              </div>
              <div className="flex items-center gap-3 whitespace-nowrap">
                <DirectionBadge direction={v.direction} />
                <span className="text-gray-600 font-mono text-xs">{timeAgo(v.captured_at)}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Mini({ label, value, hot }) {
  return (
    <div className="border border-gray-800 bg-black/30 p-2">
      <div className="text-[8px] uppercase tracking-widest text-gray-600 font-mono">{label}</div>
      <div className={`mt-1 truncate text-[10px] font-mono ${hot ? "font-bold text-amber-300" : "text-gray-300"}`}>
        {value}
      </div>
    </div>
  );
}
