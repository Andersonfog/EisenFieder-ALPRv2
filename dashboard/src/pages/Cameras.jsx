import { useEffect, useState } from "react";
import {
  apiCameras,
  apiDeleteCamera,
  apiRegisterCamera,
  apiRegenerateToken,
  apiUpdateCameraSettings,
} from "../api";
import { ALPR_PROFILES, profileById } from "../alprProfiles";
import { Card, VEHICLE_TYPES, pretty, timeAgo } from "../ui.jsx";

export default function Cameras() {
  const [cameras, setCameras] = useState([]);
  const [registering, setRegistering] = useState(false);
  const [credential, setCredential] = useState(null);
  const [settingsFor, setSettingsFor] = useState(null);

  const load = () => apiCameras().then(setCameras).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  return (
    <div className="app-page space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="page-kicker">Cameras</p>
          <h1 className="page-title">Camera fleet</h1>
          <p className="page-copy">Register USB, RTSP, or edge cameras and tune their tracking profiles.</p>
        </div>
        <button onClick={() => setRegistering(true)} className="btn-primary">
          Register camera
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cameras.map((camera) => {
          const online = camera.status === "online";
          const profile = profileById(camera.settings?.quality_profile);
          return (
            <Card key={camera.id} className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate font-semibold text-gray-100">{camera.name || camera.id}</h2>
                  <p className="mt-1 truncate text-sm text-gray-500">{camera.location || "Unlabeled location"}</p>
                  <p className="mt-1 truncate text-xs text-gray-600">{camera.id}</p>
                </div>
                <span
                  className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs ${
                    online ? "border-emerald-400/40 text-emerald-300" : "border-gray-700 text-gray-500"
                  }`}
                >
                  <span className={`led ${online ? "led-green" : ""}`} />
                  {online ? "Online" : "Idle"}
                </span>
              </div>

              <p className="mt-4 text-sm text-gray-500">
                Last seen: {camera.last_seen ? timeAgo(camera.last_seen) : "never"}
              </p>

              <div className="mt-4 grid grid-cols-3 gap-2">
                <Metric label="Profile" value={profile.short} hot />
                <Metric label="Frame" value={profile.resolution} />
                <Metric label="FPS" value={profile.fps} />
              </div>

              <div className="mt-5 flex gap-2">
                <button onClick={() => setSettingsFor(camera)} className="btn-secondary flex-1">
                  Settings
                </button>
                <button
                  onClick={() => apiRegenerateToken(camera.id).then((r) => setCredential(r)).then(load)}
                  className="btn-secondary flex-1"
                >
                  Token
                </button>
                <button
                  onClick={() => {
                    if (confirm(`Delete ${camera.id}?`)) apiDeleteCamera(camera.id).then(load);
                  }}
                  className="btn-secondary flex-1 hover:border-red-400 hover:text-red-300"
                >
                  Delete
                </button>
              </div>
            </Card>
          );
        })}
        {cameras.length === 0 && <div className="muted-empty">No cameras registered.</div>}
      </div>

      {registering && (
        <RegisterModal
          onClose={() => setRegistering(false)}
          onDone={(cred) => {
            setRegistering(false);
            setCredential(cred);
            load();
          }}
        />
      )}
      {credential && <CredentialModal cred={credential} onClose={() => setCredential(null)} />}
      {settingsFor && (
        <SettingsModal
          camera={settingsFor}
          onClose={() => setSettingsFor(null)}
          onSaved={() => {
            setSettingsFor(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function Metric({ label, value, hot }) {
  return (
    <div className="rounded-md border border-gray-800 bg-gray-950/50 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 truncate text-sm ${hot ? "font-semibold text-amber-300" : "text-gray-200"}`}>
        {value}
      </div>
    </div>
  );
}

function RegisterModal({ onClose, onDone }) {
  const [form, setForm] = useState({ serial_number: "", name: "", location: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onDone(await apiRegisterCamera(form));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Overlay onClose={onClose}>
      <h2 className="section-title">Register camera</h2>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <Input
          label="Serial"
          value={form.serial_number}
          onChange={(v) => setForm({ ...form, serial_number: v })}
          required
          placeholder="EFS-SN-00231"
        />
        <Input
          label="Name"
          value={form.name}
          onChange={(v) => setForm({ ...form, name: v })}
          placeholder="Front gate"
        />
        <Input
          label="Location"
          value={form.location}
          onChange={(v) => setForm({ ...form, location: v })}
          placeholder="Main entrance"
        />
        {error && <div className="rounded-md border border-red-400/50 bg-red-950/30 p-3 text-sm text-red-300">{error}</div>}
        <button disabled={busy} className="btn-primary w-full disabled:opacity-50">
          {busy ? "Registering..." : "Register"}
        </button>
      </form>
    </Overlay>
  );
}

function CredentialModal({ cred, onClose }) {
  return (
    <Overlay onClose={onClose}>
      <h2 className="section-title">Camera paired</h2>
      <p className="mt-2 text-sm text-gray-500">Token is shown once. Put this in the edge `.env` file.</p>
      <pre className="mt-4 max-h-64 overflow-auto rounded-md border border-gray-800 bg-gray-950 p-3 text-xs text-gray-300">
{cred.env_snippet}
      </pre>
      <button onClick={() => navigator.clipboard?.writeText(cred.env_snippet)} className="btn-secondary mt-4 w-full">
        Copy snippet
      </button>
    </Overlay>
  );
}

function SettingsModal({ camera, onClose, onSaved }) {
  const s = camera.settings || {};
  const [form, setForm] = useState({
    excluded_types: s.excluded_types || [],
    min_confidence: s.min_confidence ?? "",
    capture_plate: s.capture_plate ?? true,
    capture_occupants: s.capture_occupants ?? true,
    capture_company: s.capture_company ?? true,
    alerts_enabled: s.alerts_enabled ?? true,
    quality_profile: s.quality_profile || "workstation_track",
    enhance_plate: s.enhance_plate ?? true,
    lock_exposure: s.lock_exposure ?? true,
    edge_only: s.edge_only ?? true,
  });
  const [busy, setBusy] = useState(false);

  function toggleType(type) {
    const has = form.excluded_types.includes(type);
    setForm({
      ...form,
      excluded_types: has ? form.excluded_types.filter((x) => x !== type) : [...form.excluded_types, type],
    });
  }

  async function save() {
    setBusy(true);
    const body = {
      ...form,
      min_confidence: form.min_confidence === "" ? null : Number(form.min_confidence),
    };
    try {
      await apiUpdateCameraSettings(camera.id, body);
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  const Check = ({ k, label }) => (
    <label className="flex items-center gap-2 text-sm text-gray-300">
      <input
        type="checkbox"
        checked={form[k]}
        onChange={(e) => setForm({ ...form, [k]: e.target.checked })}
        className="h-4 w-4"
      />
      {label}
    </label>
  );

  return (
    <Overlay onClose={onClose} wide>
      <h2 className="section-title">{camera.name || camera.id}</h2>
      <p className="mt-1 text-sm text-gray-500">Camera settings</p>

      <div className="mt-5 space-y-5">
        <div>
          <div className="mb-2 text-sm font-semibold text-gray-300">Hardware profile</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {ALPR_PROFILES.map((profile) => {
              const active = form.quality_profile === profile.id;
              return (
                <button
                  key={profile.id}
                  onClick={() => setForm({ ...form, quality_profile: profile.id })}
                  className={`rounded-md border p-3 text-left transition ${
                    active
                      ? "border-amber-400/70 bg-amber-400/10 text-amber-300"
                      : "border-gray-800 bg-gray-950/60 text-gray-300 hover:border-gray-600"
                  }`}
                >
                  <div className="font-semibold">{profile.label}</div>
                  <div className="mt-1 text-xs text-gray-500">
                    {profile.resolution} at {profile.fps} fps, {profile.purpose}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <div className="mb-2 text-sm font-semibold text-gray-300">Exclude vehicle types</div>
          <div className="flex flex-wrap gap-2">
            {VEHICLE_TYPES.map((type) => {
              const off = form.excluded_types.includes(type);
              return (
                <button
                  key={type}
                  onClick={() => toggleType(type)}
                  className={`rounded-md border px-3 py-1.5 text-sm transition ${
                    off
                      ? "border-gray-700 bg-gray-950 text-gray-600 line-through"
                      : "border-gray-700 bg-gray-900 text-gray-200 hover:border-gray-500"
                  }`}
                >
                  {pretty(type)}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Check k="capture_plate" label="Read plates" />
          <Check k="capture_occupants" label="Count occupants" />
          <Check k="capture_company" label="Read company marks" />
          <Check k="alerts_enabled" label="Watchlist alerts" />
          <Check k="enhance_plate" label="Enhance plate crops" />
          <Check k="lock_exposure" label="Lock exposure" />
          <Check k="edge_only" label="Local processing" />
        </div>

        <Input
          label="Minimum confidence"
          value={form.min_confidence}
          onChange={(v) => setForm({ ...form, min_confidence: v })}
          placeholder="0.5"
        />
      </div>

      <div className="mt-6 flex justify-end gap-2">
        <button onClick={onClose} className="btn-secondary">
          Cancel
        </button>
        <button onClick={save} disabled={busy} className="btn-primary disabled:opacity-50">
          {busy ? "Saving..." : "Save"}
        </button>
      </div>
    </Overlay>
  );
}

function Overlay({ children, onClose, wide = false }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4" onClick={onClose}>
      <Card
        className={`max-h-[90vh] w-full overflow-y-auto p-6 ${wide ? "max-w-3xl" : "max-w-md"}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </Card>
    </div>
  );
}

function Input({ label, value, onChange, placeholder, required }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-gray-500">{label}</span>
      <input
        required={required}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input-control"
      />
    </label>
  );
}
