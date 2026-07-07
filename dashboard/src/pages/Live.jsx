import { useEffect, useRef, useState } from "react";
import { apiCameraLiveStatus, apiCameras, apiVehicles } from "../api";
import { ALPR_PROFILES, profileById } from "../alprProfiles";
import { Card, DirectionBadge, LiveImage, Plate, TypeBadge, timeAgo } from "../ui.jsx";

export default function Live() {
  const [cameras, setCameras] = useState([]);
  const [camId, setCamId] = useState("");
  const [status, setStatus] = useState({ online: false, age_seconds: null });
  const [events, setEvents] = useState([]);
  const [recvFps, setRecvFps] = useState(0);
  const [enhanced, setEnhanced] = useState(true);
  const [edgeOnly, setEdgeOnly] = useState(true);
  const [lockExposure, setLockExposure] = useState(true);
  const liveRef = useRef(null);

  useEffect(() => {
    apiCameras()
      .then((list) => {
        setCameras(list);
        if (list.length) setCamId((current) => current || list[0].id);
      })
      .catch(() => setCameras([]));
  }, []);

  useEffect(() => {
    if (!camId) return undefined;
    let alive = true;
    const tick = () =>
      apiCameraLiveStatus(camId)
        .then((s) => alive && setStatus(s))
        .catch(() => alive && setStatus({ online: false, age_seconds: null }));
    tick();
    const t = setInterval(tick, 1500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [camId]);

  useEffect(() => {
    if (!camId) return undefined;
    let alive = true;
    const load = () =>
      apiVehicles({ limit: 8, camera_id: camId })
        .then((r) => alive && setEvents(r.items || []))
        .catch(() => alive && setEvents([]));
    load();
    const t = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [camId]);

  const selected = cameras.find((c) => c.id === camId);
  const profileId = status.profile || selected?.settings?.quality_profile || "sharp_read";
  const profile = profileById(profileId);
  const frameSize =
    status.frame_width && status.frame_height
      ? `${status.frame_width}x${status.frame_height}`
      : profile.resolution;

  function toggleFullscreen() {
    if (!document.fullscreenElement) liveRef.current?.requestFullscreen?.();
    else document.exitFullscreen?.();
  }

  return (
    <div className="p-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="stencil text-sm text-gray-300">ALPR Command</h1>
          <p className="mt-1 text-xs text-gray-600 font-mono">
            Raspberry Pi 5 plate capture, OCR confidence, and tracking telemetry
          </p>
        </div>
        {cameras.length > 0 && (
          <div className="flex items-center gap-2">
            <select
              value={camId}
              onChange={(e) => setCamId(e.target.value)}
              className="border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-mono outline-none focus:border-amber-400"
            >
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {(c.name || c.id).toUpperCase()}
                </option>
              ))}
            </select>
            <button
              onClick={toggleFullscreen}
              className="border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-mono text-gray-400 transition hover:border-amber-400 hover:text-amber-300"
            >
              FULL
            </button>
          </div>
        )}
      </div>

      {cameras.length === 0 ? (
        <Card className="p-10 text-center text-gray-600 font-mono text-xs border-t-2 border-t-amber-400">
          -- no cameras registered --
        </Card>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_420px]">
            <div className="space-y-3">
              <div ref={liveRef} className="border border-gray-700 bg-black">
                <div className="hazard h-1.5" />
                <Card className="overflow-hidden border-0">
                  <LiveImage
                    camId={camId}
                    onFps={setRecvFps}
                    className={`aspect-video w-full ${enhanced ? "contrast-125 saturate-125" : ""}`}
                  />
                </Card>
              </div>

              <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                <FpsStat label="Console" hint="received stream" value={recvFps} good={6} />
                <FpsStat label="Capture" hint="camera frame grab" value={status.capture_fps} good={18} />
                <FpsStat label="Detect" hint="inference loop" value={status.detect_fps} good={6} />
                <FpsStat label="Source" hint={frameSize} value={status.source_fps || profile.fps} good={20} />
              </div>
            </div>

            <div className="space-y-3">
              <Card className="p-4 border-t-2 border-t-amber-400">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-gray-600 font-mono">
                      Active camera
                    </div>
                    <div className="mt-1 font-mono text-lg font-bold text-gray-100">
                      {selected?.name || camId}
                    </div>
                    <div className="mt-1 text-[10px] text-gray-600 font-mono">
                      {selected?.location || "unlabeled location"}
                    </div>
                  </div>
                  <StatusLamp online={status.online} age={status.age_seconds} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <Field label="Profile" value={profile.label} hot />
                  <Field label="Frame" value={frameSize} />
                  <Field label="JPEG" value={`${status.live_quality || profile.bitrate}`} />
                  <Field label="Queue" value={status.queued ?? "--"} />
                </div>
              </Card>

              <Card className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-[10px] uppercase tracking-widest text-gray-600 font-mono">
                    Pi 5 quality profiles
                  </h2>
                  <span className="text-[10px] font-mono text-amber-300">{profile.short}</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {ALPR_PROFILES.map((p) => (
                    <ProfileCard key={p.id} profile={p} active={p.id === profile.id} />
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <Toggle active={enhanced} onClick={() => setEnhanced(!enhanced)} label="enhance" />
                  <Toggle active={lockExposure} onClick={() => setLockExposure(!lockExposure)} label="lock ae" />
                  <Toggle active={edgeOnly} onClick={() => setEdgeOnly(!edgeOnly)} label="edge only" />
                </div>
              </Card>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
            <Card className="p-4 border-t-2 border-t-amber-400">
              <h2 className="mb-4 text-xs stencil text-gray-400">Edge Pipeline</h2>
              <div className="space-y-3">
                <PipelineRow label="Capture" value={`${status.capture_fps?.toFixed?.(1) || "--"} fps`} pct={ratePct(status.capture_fps, profile.fps)} />
                <PipelineRow label="Detector" value={`${status.detect_fps?.toFixed?.(1) || "--"} fps`} pct={ratePct(status.detect_fps, profile.processFps)} />
                <PipelineRow label="Preview" value={`${recvFps.toFixed(1)} fps`} pct={ratePct(recvFps, 12)} />
                <PipelineRow label="Plate OCR" value="multi-frame fusion" pct={82} />
                <PipelineRow label="Store/Forward" value={`${status.queued ?? 0} queued`} pct={status.queued ? 64 : 22} />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <Health label="CPU temp" value={status.cpu_temp_c ? `${status.cpu_temp_c} C` : "--"} warn={status.cpu_temp_c > 72} />
                <Health label="Mode" value={edgeOnly ? "edge" : "hybrid"} />
              </div>
            </Card>

            <Card className="overflow-hidden border-t-2 border-t-amber-400">
              <div className="flex items-center justify-between border-b border-gray-800 bg-gray-950 px-4 py-3">
                <h2 className="text-xs stencil text-gray-400">Recent Plate Reads</h2>
                <span className="text-[10px] text-gray-600 font-mono">{events.length} reads</span>
              </div>
              <div className="divide-y divide-gray-800">
                {events.map((event) => (
                  <RecentEvent key={event.id} event={event} />
                ))}
                {events.length === 0 && (
                  <div className="px-4 py-8 text-center text-xs font-mono text-gray-600">
                    -- no reads for this camera --
                  </div>
                )}
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function StatusLamp({ online, age }) {
  return (
    <div
      className={`border px-2 py-1 text-[10px] font-mono uppercase tracking-widest ${
        online ? "border-red-400/60 text-red-300" : "border-gray-700 text-gray-500"
      }`}
    >
      <span className={`led mr-1.5 ${online ? "led-red led-blink" : ""}`} />
      {online ? "streaming" : age != null ? `${age}s stale` : "offline"}
    </div>
  );
}

function FpsStat({ label, hint, value, good }) {
  const has = value != null && value > 0;
  const ok = has && value >= good;
  return (
    <Card className={`px-4 py-3 border-l-2 ${ok ? "border-l-amber-400" : "border-l-gray-700"}`}>
      <div className="flex items-center gap-2 text-[9px] uppercase tracking-widest text-gray-600 font-mono">
        <span className={`led ${ok ? "led-green" : has ? "led-amber" : ""}`} />
        {label}
      </div>
      <div className={`font-mono text-2xl mt-1 ${ok ? "text-amber-300 font-bold" : "text-gray-500"}`}>
        {has ? value.toFixed(1) : "--"}
        <span className="ml-1 text-xs font-normal text-gray-600">fps</span>
      </div>
      <div className="text-[9px] text-gray-600 mt-1 font-mono">
        {hint}
        {has && !ok ? " - below target" : ""}
      </div>
    </Card>
  );
}

function Field({ label, value, hot }) {
  return (
    <div className="border border-gray-800 bg-gray-950/60 p-2">
      <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono">{label}</div>
      <div className={`mt-1 truncate text-xs font-mono ${hot ? "font-bold text-amber-300" : "text-gray-300"}`}>
        {value ?? "--"}
      </div>
    </div>
  );
}

function ProfileCard({ profile, active }) {
  return (
    <div className={`border p-2 ${active ? "border-amber-400 bg-amber-400/10" : "border-gray-800 bg-gray-950/50"}`}>
      <div className="flex items-center justify-between gap-2">
        <div className={`font-mono text-xs font-bold ${active ? "text-amber-300" : "text-gray-300"}`}>
          {profile.short}
        </div>
        <div className="text-[9px] text-gray-600 font-mono">{profile.fps}fps</div>
      </div>
      <div className="mt-1 text-[10px] text-gray-500 font-mono">{profile.resolution}</div>
      <div className="mt-1 text-[9px] uppercase tracking-wider text-gray-600 font-mono">
        {profile.purpose}
      </div>
    </div>
  );
}

function Toggle({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      className={`border px-2 py-2 text-[10px] font-mono uppercase tracking-widest transition ${
        active
          ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-300"
          : "border-gray-700 bg-gray-950 text-gray-500 hover:border-amber-400 hover:text-amber-300"
      }`}
    >
      <span className={`led mr-1.5 ${active ? "led-green" : ""}`} />
      {label}
    </button>
  );
}

function PipelineRow({ label, value, pct }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs font-mono">
        <span className="text-gray-300">{label}</span>
        <span className="text-gray-500">{value}</span>
      </div>
      <div className="h-2 border border-gray-800 bg-gray-950">
        <div className="h-full bg-amber-400" style={{ width: `${Math.min(100, Math.max(4, pct))}%` }} />
      </div>
    </div>
  );
}

function Health({ label, value, warn }) {
  return (
    <div className="border border-gray-800 bg-gray-950/60 p-2">
      <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono">{label}</div>
      <div className={`mt-1 text-xs font-mono font-bold ${warn ? "text-red-300" : "text-gray-300"}`}>
        {value}
      </div>
    </div>
  );
}

function RecentEvent({ event }) {
  const conf = event.plate_confidence != null ? Math.round(event.plate_confidence * 100) : null;
  return (
    <div className={`grid grid-cols-[1fr_auto] gap-3 px-4 py-3 ${event.flagged ? "bg-amber-400/10" : ""}`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Plate text={event.plate_text} />
          <TypeBadge type={event.vehicle_type} />
          <DirectionBadge direction={event.direction} />
          {event.flagged && (
            <span className="bg-amber-400 px-1.5 py-0.5 text-[9px] text-black font-mono font-bold uppercase">
              ALERT
            </span>
          )}
        </div>
        <div className="mt-1 truncate text-[11px] text-gray-500 font-mono">
          {(event.vehicle_color || "unknown").toUpperCase()} {event.vehicle_make || ""}{" "}
          {event.company_name ? `- ${event.company_name}` : ""}
        </div>
      </div>
      <div className="text-right font-mono">
        <div className="text-xs font-bold text-amber-300">{conf != null ? `${conf}%` : "--"}</div>
        <div className="text-[10px] text-gray-600">{timeAgo(event.captured_at)}</div>
      </div>
    </div>
  );
}

function ratePct(value, target) {
  if (!value || !target) return 4;
  return Math.min(100, Math.round((value / target) * 100));
}
