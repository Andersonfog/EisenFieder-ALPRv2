import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { Led } from "../ui.jsx";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/live", label: "Live Monitor" },
  { to: "/vehicles", label: "Plate Log" },
  { to: "/insights", label: "Insights" },
  { to: "/watchlist", label: "Watchlist" },
  { to: "/cameras", label: "Cameras" },
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
      <aside className="flex w-64 flex-col border-r border-gray-800 bg-gray-950/95">
        <div className="border-b border-gray-800 px-5 py-5">
          <div className="text-lg font-semibold text-gray-50">EisenFieder ALPR</div>
          <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
            <Led color="green" />
            Local operations console
          </div>
        </div>

        <nav className="flex-1 px-3 py-4">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `mb-1 flex items-center justify-between rounded-md px-3 py-2.5 text-sm transition ${
                  isActive
                    ? "bg-gray-800 text-gray-50"
                    : "text-gray-400 hover:bg-gray-900 hover:text-gray-100"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-gray-800 px-4 py-4">
          <div className="mb-3 text-xs text-gray-500">Signed in as</div>
          <div className="mb-3 truncate text-sm text-gray-300">{user?.email}</div>
          <button
            onClick={handleLogout}
            className="w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-300 transition hover:border-gray-500 hover:bg-gray-800"
          >
            Sign out
          </button>
        </div>
      </aside>

      <main className="flex flex-1 flex-col overflow-y-auto">
        <div className="flex-1">
          <Outlet />
        </div>
        <footer className="border-t border-gray-800 bg-gray-950/90 px-8 py-4 text-xs text-gray-500">
          <div className="flex items-center gap-4">
            <a href="/policy" className="transition hover:text-gray-300">Policy</a>
            <a href="/terms" className="transition hover:text-gray-300">Terms</a>
            <span>On-premises vehicle intelligence</span>
            <span className="ml-auto flex items-center gap-2">
              <Led color="green" /> Backend connected
            </span>
          </div>
        </footer>
      </main>
    </div>
  );
}
