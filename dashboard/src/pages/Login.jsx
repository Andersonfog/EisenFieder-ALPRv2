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
    "w-full rounded-md border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none transition focus:border-amber-400";

  return (
    <div className="flex h-screen items-center justify-center bg-shop-floor px-4">
      <div className="w-full max-w-md">
        <div className="panel overflow-hidden">
          <div className="border-b border-gray-800 px-7 py-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold text-gray-50">EisenFieder ALPR</h1>
                <p className="mt-1 text-sm text-gray-500">Owner console sign in</p>
              </div>
              <span className="inline-flex items-center gap-2 rounded-full border border-gray-700 bg-gray-950 px-3 py-1 text-xs text-gray-400">
                <Led color="amber" /> Local
              </span>
            </div>
          </div>

          <form onSubmit={onSubmit} className="space-y-4 p-7">
            <div>
              <label className="mb-1 block text-sm text-gray-400">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={input}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-gray-400">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={input}
              />
            </div>
            {error && (
              <div className="rounded-md border border-red-400/50 bg-red-950/30 px-3 py-2 text-sm text-red-300">
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-md bg-amber-400 px-4 py-2.5 text-sm font-semibold text-gray-950 transition hover:bg-amber-300 disabled:opacity-50"
            >
              {busy ? "Signing in..." : "Sign in"}
            </button>
            <p className="text-center text-xs text-gray-600">
              Footage and vehicle records stay on the local system.
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
