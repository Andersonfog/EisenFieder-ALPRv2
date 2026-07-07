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
  const profileId = status.profile || selected?.settings?.quality_profile || "workstation_track";
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
    <div className="space-y-6 p-6 lg:p-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-gray-500">Live Monitor</p>
          <h1 className="mt-1 text-2xl font-semibold text-gray-50">
            {selected?.name || "Camera feed"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Track continuity, plate reads, and live stream health for the selected camera.
          </p>
        </div>
        {cameras.length > 0 && (
          <div className="flex items-center gap-2">
            <select
              value={camId}
              onChange={(e) => setCamId(e.target.value)}
              className="rounded-md border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-200 outline-none focus:border-amber-400"
            >
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name || c.id}
                </option>
              ))}
            </select>
            <button
              onClick={toggleFullscreen}
              className="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-300 transition hover:border-gray-500 hover:bg-gray-800"
            >
              Fullscreen
            </button>
          </div>
        )}
      </div>

      {cameras.length === 0 ? (
        <Card className="p-10 text-center text-sm text-gray-500">
          No cameras registered.
        </Card>
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_420px]">
            <section className="space-y-4">
              <div ref={liveRef}>
                <Card className="overflow-hidden p-3">
                  <LiveImage
                    camId={camId}
                    onFps={setRecvFps}
                    className={`aspect-video w-full ${enhanced ? "contrast-110 saturate-110" : ""}`}
                  />
                </Card>
              </div>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <FpsStat label="Console stream" hint="received" value={recvFps} target={12} />
                <FpsStat label="Capture" hint="camera input" value={status.capture_fps} target={profile.fps} />
                <FpsStat label="Detector" hint="inference loop" value={status.detect_fps} target={profile.processFps} />
                <FpsStat label="Source" hint={frameSize} value={status.source_fps || profile.fps} target={profile.fps} />
              </div>
            </section>

            <aside className="space-y-4">
              <Card className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm text-gray-500">Active camera</p>
                    <h2 className="mt-1 text-lg font-semibold text-gray-100">
                      {selected?.name || camId}
                    </h2>
                    <p className="mt-1 text-sm text-gray-500">
                      {selected?.location || "Unlabeled location"}
                    </p>
                  </div>
                  <StatusLamp online={status.online} age={status.age_seconds} />
                </div>
                <div className="mt-5 grid grid-cols-2 gap-3">
                  <Field label="Profile" value={profile.label} hot />
                  <Field label="Frame" value={frameSize} />
                  <Field label="Preview" value={`${status.live_quality || profile.bitrate}`} />
                  <Field label="Queue" value={status.queued ?? "--"} />
                </div>
              </Card>

              <Card className="p-5">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-200">Hardware profile</h2>
                  <span className="rounded-md bg-gray-800 px-2 py-1 text-xs text-gray-400">
                    {profile.short}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {ALPR_PROFILES.map((p) => (
                    <ProfileCard key={p.id} profile={p} active={p.id === profile.id} />
                  ))}
                </div>
                <button
                  onClick={() => setEnhanced(!enhanced)}
                  className={`mt-4 w-full rounded-md border px-3 py-2 text-sm transition ${
                    enhanced
                      ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
                      : "border-gray-700 bg-gray-900 text-gray-400 hover:border-gray-500"
                  }`}
                >
                  Preview enhancement {enhanced ? "on" : "off"}
                </button>
              </Card>
            </aside>
          </div>

          <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
            <Card className="p-5">
              <h2 className="mb-4 text-sm font-semibold text-gray-200">Pipeline</h2>
              <div className="space-y-4">
                <PipelineRow label="Capture" value={`${status.capture_fps?.toFixed?.(1) || "--"} fps`} pct={ratePct(status.capture_fps, profile.fps)} />
                <PipelineRow label="Detector" value={`${status.detect_fps?.toFixed?.(1) || "--"} fps`} pct={ratePct(status.detect_fps, profile.processFps)} />
                <PipelineRow label="Preview" value={`${recvFps.toFixed(1)} fps`} pct={ratePct(recvFps, 12)} />
                <PipelineRow label="Plate OCR" value="multi-frame fusion" pct={82} />
                <PipelineRow label="Store/forward" value={`${status.queued ?? 0} queued`} pct={status.queued ? 64 : 22} />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3">
                <Health label="CPU temp" value={status.cpu_temp_c ? `${status.cpu_temp_c} C` : "--"} warn={status.cpu_temp_c > 72} />
                <Health label="Processing" value="local" />
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-gray-800 px-5 py-4">
                <h2 className="text-sm font-semibold text-gray-200">Recent reads</h2>
                <span className="text-xs text-gray-500">{events.length} records</span>
              </div>
              <div className="divide-y divide-gray-800">
                {events.map((event) => (
                  <RecentEvent key={event.id} event={event} />
                ))}
                {events.length === 0 && (
                  <div className="px-5 py-8 text-center text-sm text-gray-500">
                    No reads for this camera yet.
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
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
        online ? "border-red-400/50 text-red-300" : "border-gray-700 text-gray-500"
      }`}
    >
      <span className={`led ${online ? "led-red led-blink" : ""}`} />
      {online ? "Streaming" : age != null ? `${age}s stale` : "Offline"}
    </div>
  );
}

function FpsStat({ label, hint, value, target }) {
  const has = value != null && value > 0;
  const ok = has && value >= Math.max(1, target * 0.45);
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span className={`led ${ok ? "led-green" : has ? "led-amber" : ""}`} />
        {label}
      </div>
      <div className={`mt-2 text-2xl font-semibold ${ok ? "text-gray-50" : "text-gray-500"}`}>
        {has ? value.toFixed(1) : "--"}
        <span className="ml-1 text-xs font-normal text-gray-500">fps</span>
      </div>
      <div className="mt-1 text-xs text-gray-600">{hint}</div>
    </Card>
  );
}

function Field({ label, value, hot }) {
  return (
    <div className="rounded-md border border-gray-800 bg-gray-950/60 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 truncate text-sm ${hot ? "font-semibold text-amber-300" : "text-gray-300"}`}>
        {value ?? "--"}
      </div>
    </div>
  );
}

function ProfileCard({ profile, active }) {
  return (
    <div className={`rounded-md border p-3 ${active ? "border-amber-400/60 bg-amber-400/10" : "border-gray-800 bg-gray-950/50"}`}>
      <div className="flex items-center justify-between gap-2">
        <div className={`text-xs font-semibold ${active ? "text-amber-300" : "text-gray-300"}`}>
          {profile.short}
        </div>
        <div className="text-xs text-gray-600">{profile.fps} fps</div>
      </div>
      <div className="mt-1 text-xs text-gray-500">{profile.resolution}</div>
      <div className="mt-1 text-xs text-gray-600">{profile.purpose}</div>
    </div>
  );
}

function PipelineRow({ label, value, pct }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-sm">
        <span className="text-gray-300">{label}</span>
        <span className="text-gray-500">{value}</span>
      </div>
      <div className="h-2 rounded-full bg-gray-800">
        <div className="h-full rounded-full bg-amber-400" style={{ width: `${Math.min(100, Math.max(4, pct))}%` }} />
      </div>
    </div>
  );
}

function Health({ label, value, warn }) {
  return (
    <div className="rounded-md border border-gray-800 bg-gray-950/60 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 text-sm font-semibold ${warn ? "text-red-300" : "text-gray-300"}`}>
        {value}
      </div>
    </div>
  );
}

function RecentEvent({ event }) {
  const conf = event.plate_confidence != null ? Math.round(event.plate_confidence * 100) : null;
  return (
    <div className={`grid grid-cols-[1fr_auto] gap-3 px-5 py-4 ${event.flagged ? "bg-amber-400/10" : ""}`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Plate text={event.plate_text} />
          <TypeBadge type={event.vehicle_type} />
          <DirectionBadge direction={event.direction} />
          {event.flagged && (
            <span className="rounded-md bg-amber-400 px-2 py-0.5 text-xs font-semibold text-gray-950">
              Alert
            </span>
          )}
        </div>
        <div className="mt-2 truncate text-sm text-gray-500">
          {(event.vehicle_color || "unknown")} {event.vehicle_make || ""}{" "}
          {event.company_name ? `- ${event.company_name}` : ""}
        </div>
      </div>
      <div className="text-right">
        <div className="text-sm font-semibold text-amber-300">{conf != null ? `${conf}%` : "--"}</div>
        <div className="text-xs text-gray-600">{timeAgo(event.captured_at)}</div>
      </div>
    </div>
  );
}

function ratePct(value, target) {
  if (!value || !target) return 4;
  return Math.min(100, Math.round((value / target) * 100));
}
