import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router";
import { api } from "./api";
import { useLoad } from "./components/ui";
import { SharedProvider, useShared } from "./context";
import Browse from "./pages/Browse";
import Decision from "./pages/Decision";
import Version from "./pages/Version";
import Versions from "./pages/Versions";
import { USERS } from "./roles";
import "./styles.css";

function Header() {
  const { user, setUser, live } = useShared();
  const health = useLoad(api.health, []);
  return (
    <>
      <header className="top">
        <span className="brand">Policy labeling</span>
        <nav>
          <NavLink to="/" end>Labels</NavLink>
          <NavLink to="/versions">Versions</NavLink>
        </nav>
        {live && <span className="pill">Live policy <b>{live}</b></span>}
        <label className="acting">
          Acting as{" "}
          <select
            aria-label="Acting as"
            value={user.key}
            onChange={(e) => setUser(USERS.find((u) => u.key === e.target.value)!)}
          >
            {USERS.map((u) => (
              <option key={u.key} value={u.key}>{u.name}, {u.role}</option>
            ))}
          </select>
        </label>
      </header>
      {health.data && !health.data.live_labeling && (
        <div className="banner" role="status">
          Live labeling is off: {health.data.missing_keys.join(", ")} not set. Postings are accepted and wait in the queue.
        </div>
      )}
    </>
  );
}

function App() {
  const { user } = useShared();
  return (
    <>
      <Header />
      {/* key: switching user reloads the page's data with the new role */}
      <Routes key={user.key}>
        <Route path="/" element={<Browse />} />
        <Route path="/labels/:id" element={<Decision />} />
        <Route path="/versions" element={<Versions />} />
        <Route path="/versions/:name" element={<Version />} />
        <Route path="*" element={<p className="page">Page not found.</p>} />
      </Routes>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <SharedProvider>
        <App />
      </SharedProvider>
    </BrowserRouter>
  </StrictMode>,
);
