import { useEffect, useState } from "react";
import {
  apiCameras, apiDeleteCamera, apiRegisterCamera, apiRegenerateToken,
  apiUpdateCameraSettings,
} from "../api";
import { ALPR_PROFILES, profileById } from "../alprProfiles";
import { Card, VEHICLE_TYPES, formatTime, pretty, timeAgo } from "../ui.jsx";

export default function Cameras() {
  const [cameras, setCameras] = useState([]);
  const [registering, setRegistering] = useState(false);
  const [credential, setCredential] = useState(null); // {id, api_token, env_snippet}
  const [settingsFor, setSettingsFor] = useState(null);

  const load = () => apiCameras().then(setCameras).catch(() => {});
  useEffect(() => { load(); }, []);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="stencil text-sm text-gray-400">Cameras</h1>
          <p className="mt-1 text-xs text-gray-600 font-mono">Entrance units reporting to system</p>
        </div>
        <button
          onClick={() => setRegistering(true)}
          className="border border-amber-500 bg-amber-400 px-4 py-2 text-xs font-mono uppercase font-bold tracking-widest text-black hover:bg-amber-300 transition"
        >
          Register
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {cameras.map((c) => {
          const online = c.status === "online";
          const profile = profileById(c.settings?.quality_profile);
          return (
            <Card key={c.id} className={`p-4 border-t-2 ${online ? "border-t-amber-400" : "border-t-gray-700"}`}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold text-gray-200">{c.name || c.id}</div>
                  <div className="font-mono text-[10px] text-gray-600 mt-1">{c.id}</div>
                  {c.location && (
                    <div className="text-[10px] text-gray-600 mt-1">{c.location}</div>
                  )}
                </div>
                <span
                  className={`inline-flex items-center gap-1.5 border px-1.5 py-0.5 text-[10px] uppercase font-mono ${
                    online
                      ? "border-emerald-400/50 bg-gray-950 text-emerald-300 font-bold"
                      : "border-gray-700 bg-gray-950 text-gray-500"
                  }`}
                >
                  <span className={`led ${online ? "led-green" : ""}`} />
                  {c.status}
                </span>
              </div>
              <div className="mt-2 text-[10px] text-gray-600 font-mono">
                last: {c.last_seen ? timeAgo(c.last_seen) : "never"}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-1 text-[10px] font-mono">
                <div className="border border-gray-800 bg-gray-950/60 p-2">
                  <div className="text-gray-600 uppercase tracking-widest">profile</div>
                  <div className="mt-1 font-bold text-amber-300">{profile.short}</div>
                </div>
                <div className="border border-gray-800 bg-gray-950/60 p-2">
                  <div className="text-gray-600 uppercase tracking-widest">res</div>
                  <div className="mt-1 text-gray-300">{profile.resolution}</div>
                </div>
                <div className="border border-gray-800 bg-gray-950/60 p-2">
                  <div className="text-gray-600 uppercase tracking-widest">fps</div>
                  <div className="mt-1 text-gray-300">{profile.fps}</div>
                </div>
              </div>
              <div className="mt-3 flex gap-1">
                <button
                  onClick={() => setSettingsFor(c)}
                  className="border border-gray-700 bg-gray-950 px-2 py-1 text-[10px] font-mono text-gray-400 hover:border-amber-400 hover:text-amber-300 transition flex-1"
                >
                  CFG
                </button>
                <button
                  onClick={() =>
                    apiRegenerateToken(c.id).then((r) => setCredential(r)).then(load)
                  }
                  className="border border-gray-700 bg-gray-950 px-2 py-1 text-[10px] font-mono text-gray-400 hover:border-amber-400 hover:text-amber-300 transition flex-1"
                >
                  KEY
                </button>
                <button
                  onClick={() => {
                    if (confirm(`Delete ${c.id}?`)) apiDeleteCamera(c.id).then(load);
                  }}
                  className="border border-gray-700 bg-gray-950 px-2 py-1 text-[10px] font-mono text-gray-400 hover:border-red-400 hover:text-red-300 transition flex-1"
                >
                  DEL
                </button>
              </div>
            </Card>
          );
        })}
        {cameras.length === 0 && (
          <div className="text-xs text-gray-600 font-mono">
            — no cameras registered —
          </div>
        )}
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
      {credential && (
        <CredentialModal cred={credential} onClose={() => setCredential(null)} />
      )}
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
      <h2 className="mb-4 text-xs stencil text-gray-300">Register Camera</h2>
      <form onSubmit={submit} className="space-y-3">
        <Input label="Serial" value={form.serial_number}
          onChange={(v) => setForm({ ...form, serial_number: v })} required
          placeholder="EFS-SN-00231" />
        <Input label="Name" value={form.name}
          onChange={(v) => setForm({ ...form, name: v })} placeholder="FRONT GATE" />
        <Input label="Location" value={form.location}
          onChange={(v) => setForm({ ...form, location: v })} placeholder="MAIN ENTRANCE" />
        {error && (
          <div className="border border-red-400/60 bg-red-950/40 px-2 py-1 text-xs font-mono font-bold uppercase text-red-300">
            {error}
          </div>
        )}
        <button
          disabled={busy}
          className="w-full border border-amber-500 bg-amber-400 px-4 py-2 text-xs font-mono uppercase font-bold tracking-widest text-black hover:bg-amber-300 disabled:opacity-40 transition"
        >
          {busy ? "Registering…" : "Register"}
        </button>
      </form>
    </Overlay>
  );
}

function CredentialModal({ cred, onClose }) {
  return (
    <Overlay onClose={onClose}>
      <h2 className="mb-2 text-xs stencil text-gray-300">Camera Paired</h2>
      <p className="mb-4 text-xs text-gray-600 font-mono">
        Copy into .env file. Token shown <span className="text-amber-300 font-bold">only once</span>.
      </p>
      <pre className="overflow-x-auto border border-gray-700 bg-gray-950 p-3 text-[11px] text-gray-300 font-mono break-words whitespace-pre-wrap">
{cred.env_snippet}
      </pre>
      <button
        onClick={() => navigator.clipboard?.writeText(cred.env_snippet)}
        className="mt-3 w-full border border-gray-700 bg-gray-950 px-3 py-1.5 text-xs font-mono text-gray-400 hover:border-amber-400 hover:text-amber-300 transition"
      >
        COPY
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
    quality_profile: s.quality_profile || "sharp_read",
    enhance_plate: s.enhance_plate ?? true,
    lock_exposure: s.lock_exposure ?? true,
    edge_only: s.edge_only ?? true,
  });
  const [busy, setBusy] = useState(false);

  function toggleType(t) {
    const has = form.excluded_types.includes(t);
    setForm({
      ...form,
      excluded_types: has
        ? form.excluded_types.filter((x) => x !== t)
        : [...form.excluded_types, t],
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
    <label className="flex items-center gap-2 text-xs font-mono text-gray-300 cursor-pointer">
      <input
        type="checkbox"
        checked={form[k]}
        onChange={(e) => setForm({ ...form, [k]: e.target.checked })}
        className="w-4 h-4"
      />
      {label}
    </label>
  );

  return (
    <Overlay onClose={onClose}>
      <h2 className="mb-1 text-xs stencil text-gray-300">{camera.name || camera.id}</h2>
      <p className="mb-4 text-[10px] text-gray-600 font-mono">ALPR camera settings</p>

      <div className="space-y-4 text-xs">
        <div>
          <div className="mb-2 text-[10px] uppercase tracking-widest text-gray-600 font-mono">
            Pi 5 quality profile
          </div>
          <div className="grid grid-cols-2 gap-2">
            {ALPR_PROFILES.map((p) => {
              const active = form.quality_profile === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => setForm({ ...form, quality_profile: p.id })}
                  className={`border p-2 text-left transition ${
                    active
                      ? "border-amber-400 bg-amber-400/10 text-amber-300"
                      : "border-gray-800 bg-gray-950 text-gray-400 hover:border-amber-400 hover:text-amber-300"
                  }`}
                >
                  <div className="font-mono text-xs font-bold">{p.short}</div>
                  <div className="mt-1 text-[10px] text-gray-600">{p.resolution} @ {p.fps}fps</div>
                  <div className="mt-1 text-[9px] uppercase tracking-wider text-gray-600">
                    {p.purpose}
                  </div>
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] text-gray-600 font-mono">
            Edge units apply profile changes on their next config pull/restart.
          </p>
        </div>

        <div>
          <div className="mb-2 text-[10px] uppercase tracking-widest text-gray-600 font-mono">
            Exclude types
          </div>
          <div className="flex flex-wrap gap-1">
            {VEHICLE_TYPES.map((t) => {
              const off = form.excluded_types.includes(t);
              return (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={`border px-2 py-1 text-[10px] uppercase font-mono transition ${
                    off
                      ? "border-gray-700 bg-gray-950 text-gray-600 line-through"
                      : "border-gray-500 bg-gray-900 text-gray-200 hover:border-amber-400 hover:text-amber-300"
                  }`}
                >
                  {pretty(t).slice(0, 3)}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Check k="capture_plate" label="READ PLATES" />
          <Check k="capture_occupants" label="COUNT" />
          <Check k="capture_company" label="COMPANY" />
          <Check k="alerts_enabled" label="ALERTS" />
          <Check k="enhance_plate" label="ENHANCE PLATE" />
          <Check k="lock_exposure" label="LOCK EXPOSURE" />
          <Check k="edge_only" label="EDGE ONLY" />
        </div>

        <Input
          label="Min confidence"
          value={form.min_confidence}
          onChange={(v) => setForm({ ...form, min_confidence: v })}
          placeholder="0.5"
        />
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="border border-gray-700 bg-gray-950 px-4 py-1.5 text-xs font-mono uppercase text-gray-400 hover:border-amber-400 hover:text-amber-300 transition">
          CANCEL
        </button>
        <button
          onClick={save}
          disabled={busy}
          className="border border-amber-500 bg-amber-400 px-4 py-1.5 text-xs font-mono uppercase font-bold tracking-widest text-black hover:bg-amber-300 disabled:opacity-40 transition"
        >
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </Overlay>
  );
}

function Overlay({ children, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <Card className="w-full max-w-md p-6 border-t-4 border-t-amber-400" onClick={(e) => e.stopPropagation()}>
        {children}
      </Card>
    </div>
  );
}

function Input({ label, value, onChange, placeholder, required }) {
  return (
    <div>
      <label className="mb-1 block text-[10px] font-mono uppercase tracking-widest text-gray-600">{label}</label>
      <input
        required={required}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-mono outline-none focus:border-amber-400 placeholder-gray-600"
      />
    </div>
  );
}
