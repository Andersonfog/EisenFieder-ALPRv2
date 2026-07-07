import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { Led } from "../ui.jsx";

const NAV = [
  { to: "/", label: "ALPR Status", end: true, n: "01" },
  { to: "/insights", label: "Insights", n: "02" },
  { to: "/live", label: "ALPR Command", n: "03" },
  { to: "/vehicles", label: "Plate Log", n: "04" },
  { to: "/watchlist", label: "Watchlist", n: "05" },
  { to: "/cameras", label: "Pi Cameras", n: "06" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="flex h-screen overflow-hidden bg-shop-floor text-gray-200">
      <aside className="flex w-56 flex-col border-r border-gray-700 bg-gray-950">
        <div className="hazard h-1.5" />
        <div className="border-b border-gray-700 px-4 py-4">
          <div className="stencil text-sm text-gray-100">EISENFIEDER</div>
          <div className="mt-1 flex items-center gap-2">
            <Led color="green" />
            <span className="text-[10px] uppercase tracking-widest text-gray-500">
              ALPR Edge Unit
            </span>
          </div>
        </div>
        <nav className="mt-0 flex-1 space-y-0 px-0">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center gap-3 border-l-2 px-4 py-2.5 text-xs font-mono uppercase tracking-wide transition ${
                  isActive
                    ? "border-l-amber-400 bg-gray-900 text-amber-300 font-bold"
                    : "border-l-transparent text-gray-400 hover:border-l-gray-500 hover:bg-gray-900/60 hover:text-gray-100"
                }`
              }
            >
              <span className="w-5 text-[10px] tabular-nums opacity-60">{n.n}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-gray-700 px-4 py-3">
          <div className="mb-2 flex items-center gap-2">
            <Led color="amber" />
            <span className="truncate font-mono text-[11px] text-gray-500">{user?.email}</span>
          </div>
          <button
            onClick={handleLogout}
            className="w-full border border-gray-600 bg-gray-900 px-3 py-1.5 text-[11px] font-mono uppercase tracking-widest text-gray-400 transition hover:border-amber-400 hover:text-amber-300"
          >
            logout
          </button>
        </div>
        <div className="hazard h-1.5" />
      </aside>

      <main className="flex flex-1 flex-col overflow-y-auto bg-shop-floor">
        <div className="flex-1">
          <Outlet />
        </div>
        <footer className="border-t border-gray-800 bg-gray-950 px-8 py-4 text-[10px] font-mono text-gray-600">
          <div className="flex items-center gap-4">
            <a href="/policy" className="transition hover:text-amber-300">policy</a>
            <a href="/terms" className="transition hover:text-amber-300">terms</a>
            <span>© eisenfieder surveillance</span>
            <span className="ml-auto flex items-center gap-2 uppercase tracking-widest">
              <Led color="green" /> system nominal
            </span>
          </div>
        </footer>
      </main>
    </div>
  );
}
