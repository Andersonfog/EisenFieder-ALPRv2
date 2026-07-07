import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { Led } from "../ui.jsx";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("owner@eisenfieder.local");
  const [password, setPassword] = useState("changeme123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full border border-gray-700 bg-gray-950 px-3 py-2 text-sm font-mono text-gray-200 outline-none transition focus:border-amber-400";

  return (
    <div className="flex h-screen items-center justify-center bg-shop-floor px-4">
      <div className="w-full max-w-sm">
        <div className="panel">
          <div className="hazard h-2" />
          <div className="border-b border-gray-700 px-6 py-5 text-center">
            <h1 className="stencil text-lg text-gray-100">EISENFIEDER</h1>
            <p className="mt-1 flex items-center justify-center gap-2 text-xs uppercase tracking-widest text-gray-500">
              <Led color="amber" blink /> Surveillance Console
            </p>
          </div>
          <form onSubmit={onSubmit} className="space-y-4 p-6">
            <div>
              <label className="mb-1 block text-xs font-mono uppercase tracking-widest text-gray-500">
                email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={input}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-mono uppercase tracking-widest text-gray-500">
                password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={input}
              />
            </div>
            {error && (
              <div className="border border-red-400/60 bg-red-950/40 px-3 py-2 text-xs font-mono font-bold uppercase text-red-300">
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={busy}
              className="w-full border border-amber-500 bg-amber-400 px-4 py-2 text-xs font-mono font-bold uppercase tracking-widest text-black transition hover:bg-amber-300 disabled:opacity-40"
            >
              {busy ? "authenticating..." : "Authenticate"}
            </button>
            <p className="text-center text-[10px] font-mono uppercase text-gray-600">
              owner access only · encrypted · private
            </p>
          </form>
          <div className="hazard h-2" />
        </div>
      </div>
    </div>
  );
}
