import { useEffect, useState } from "react";
import { apiAddWatch, apiDeleteWatch, apiToggleWatch, apiWatchlist } from "../api";
import { Card, Plate, formatTime } from "../ui.jsx";

export default function Watchlist() {
  const [entries, setEntries] = useState([]);
  const [form, setForm] = useState({ plate_text: "", label: "", reason: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => apiWatchlist().then(setEntries).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await apiAddWatch(form);
      setForm({ plate_text: "", label: "", reason: "" });
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="stencil text-sm text-gray-400">Watchlist</h1>
        <p className="mt-1 text-xs text-gray-600 font-mono">
          Flag plates for automatic alerts on matching vehicles
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5 border-t-2 border-t-amber-400">
          <h2 className="mb-3 text-xs stencil text-gray-500">Add plate</h2>
          <form onSubmit={add} className="space-y-3">
            <input
              required
              placeholder="PLATE"
              value={form.plate_text}
              onChange={(e) => setForm({ ...form, plate_text: e.target.value })}
              className="w-full border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-mono outline-none focus:border-amber-400 placeholder-gray-600"
            />
            <input
              placeholder="LABEL"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              className="w-full border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-mono outline-none focus:border-amber-400 placeholder-gray-600"
            />
            <input
              placeholder="REASON (OPT)"
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              className="w-full border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-mono outline-none focus:border-amber-400 placeholder-gray-600"
            />
            {error && (
              <div className="border border-red-400/60 bg-red-950/40 px-2 py-1 text-xs font-mono font-bold uppercase text-red-300">
                {error}
              </div>
            )}
            <button
              disabled={busy}
              className="w-full border border-amber-500 bg-amber-400 px-4 py-2 text-xs font-mono uppercase font-bold tracking-widest text-black hover:bg-amber-300 disabled:opacity-40 transition"
            >
              {busy ? "Adding…" : "Add"}
            </button>
          </form>
        </Card>

        <Card className="p-0 lg:col-span-2 border-t-2 border-t-amber-400 overflow-hidden">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-gray-950 text-gray-600 border-b border-gray-700">
              <tr>
                <th className="px-4 py-2 uppercase tracking-widest">Plate</th>
                <th className="px-4 py-2 uppercase tracking-widest">Label</th>
                <th className="px-4 py-2 uppercase tracking-widest">Added</th>
                <th className="px-4 py-2 uppercase tracking-widest">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((w) => (
                <tr key={w.id} className="border-t border-gray-800 hover:bg-gray-900/50">
                  <td className="px-4 py-2"><Plate text={w.plate_text} /></td>
                  <td className="px-4 py-2 text-gray-300">
                    {w.label || "–"}
                    {w.reason && <div className="text-[10px] text-gray-600">{w.reason}</div>}
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-[10px]">{formatTime(w.created_at).split(' ')[1] || "–"}</td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => apiToggleWatch(w.id, !w.active).then(load)}
                      className={`inline-flex items-center gap-1.5 border px-2 py-1 text-[10px] uppercase font-mono ${
                        w.active
                          ? "border-amber-500 bg-amber-400 text-black font-bold"
                          : "border-gray-700 bg-gray-950 text-gray-500"
                      } transition`}
                    >
                      <span className={`led ${w.active ? "led-red" : ""}`} />
                      {w.active ? "ARMED" : "OFF"}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => apiDeleteWatch(w.id).then(load)}
                      className="text-gray-600 hover:text-white transition"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
              {entries.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-600">
                    — no entries —
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
