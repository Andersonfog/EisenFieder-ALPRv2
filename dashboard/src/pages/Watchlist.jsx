import { useEffect, useState } from "react";
import { apiAddWatch, apiDeleteWatch, apiToggleWatch, apiWatchlist } from "../api";
import { Card, Plate, formatTime } from "../ui.jsx";

export default function Watchlist() {
  const [entries, setEntries] = useState([]);
  const [form, setForm] = useState({ plate_text: "", label: "", reason: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => apiWatchlist().then(setEntries).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

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
    <div className="app-page space-y-6">
      <div>
        <p className="page-kicker">Watchlist</p>
        <h1 className="page-title">Alert plates</h1>
        <p className="page-copy">Flag plates for automatic alerts when matching vehicles are captured.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="p-5">
          <h2 className="section-title">Add plate</h2>
          <form onSubmit={add} className="mt-4 space-y-3">
            <input
              required
              placeholder="Plate"
              value={form.plate_text}
              onChange={(e) => setForm({ ...form, plate_text: e.target.value })}
              className="input-control"
            />
            <input
              placeholder="Label"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              className="input-control"
            />
            <input
              placeholder="Reason"
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              className="input-control"
            />
            {error && <div className="rounded-md border border-red-400/50 bg-red-950/30 p-3 text-sm text-red-300">{error}</div>}
            <button disabled={busy} className="btn-primary w-full disabled:opacity-50">
              {busy ? "Adding..." : "Add plate"}
            </button>
          </form>
        </Card>

        <Card className="table-shell">
          <table className="data-table">
            <thead>
              <tr>
                <th>Plate</th>
                <th>Label</th>
                <th>Added</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td>
                    <Plate text={entry.plate_text} />
                  </td>
                  <td className="text-gray-300">
                    {entry.label || "-"}
                    {entry.reason && <div className="mt-1 text-xs text-gray-500">{entry.reason}</div>}
                  </td>
                  <td className="text-gray-500">{formatTime(entry.created_at).split(" ")[1] || "-"}</td>
                  <td>
                    <button
                      onClick={() => apiToggleWatch(entry.id, !entry.active).then(load)}
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
                        entry.active
                          ? "border-red-400/50 bg-red-400/10 text-red-300"
                          : "border-gray-700 bg-gray-950 text-gray-500"
                      }`}
                    >
                      <span className={`led ${entry.active ? "led-red" : ""}`} />
                      {entry.active ? "Armed" : "Off"}
                    </button>
                  </td>
                  <td className="text-right">
                    <button
                      onClick={() => apiDeleteWatch(entry.id).then(load)}
                      className="btn-secondary px-3 py-1.5 text-sm"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {entries.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center text-gray-500">
                    No watchlist entries.
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
