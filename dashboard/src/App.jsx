import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Layout from "./components/Layout.jsx";
import Login from "./pages/Login.jsx";
import Overview from "./pages/Overview.jsx";
import Insights from "./pages/Insights.jsx";
import Live from "./pages/Live.jsx";
import Vehicles from "./pages/Vehicles.jsx";
import Watchlist from "./pages/Watchlist.jsx";
import Cameras from "./pages/Cameras.jsx";
import Policy from "./pages/Policy.jsx";
import Terms from "./pages/Terms.jsx";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950 text-sm text-gray-400">
        Loading...
      </div>
    );
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route index element={<Overview />} />
        <Route path="insights" element={<Insights />} />
        <Route path="live" element={<Live />} />
        <Route path="vehicles" element={<Vehicles />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="policy" element={<Policy />} />
        <Route path="terms" element={<Terms />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
