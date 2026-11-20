import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router";
import { api } from "./api";
import { Chevron, SidePanel } from "./components/SidePanel";
import { useLoad } from "./components/ui";
import { SharedProvider, useShared } from "./context";
import Browse from "./pages/Browse";
import Compare from "./pages/Compare";
import Decision from "./pages/Decision";
import Version from "./pages/Version";
import Versions from "./pages/Versions";
import "./styles.css";

function Header() {
  const { user, live, viewing, setPanelOpen } = useShared();
  const health = useLoad(api.health, []);
  return (
    <>
      <header className="top">
        <span className="brand">Policy labeling</span>
        <nav>
          <NavLink to="/" end>Labels</NavLink>
          <NavLink to="/versions">Versions</NavLink>
        </nav>
        {live && (
          <span className="viewing" data-testid="viewing">
            Showing policy <b>{viewing ?? live}</b>
            {viewing ? <> · live is <b>{live}</b></> : " (live)"}
          </span>
        )}
        <span className="acting">
          <button className="whoami" onClick={() => setPanelOpen(true)} title="Change who you are in the side panel">
            <b>{user.name}</b> · {user.role}
          </button>
        </span>
      </header>
      {health.data?.llm_backend === "fake" && (
        <div className="banner sample" role="status">
          Sample mode: labels come from a stand-in that matches fixed words, not from Claude. Run <code>make demo</code> for real labels.
        </div>
      )}
      {health.data && !health.data.live_labeling && (
        <div className="banner" role="status">
          Live labeling is off: {health.data.missing_keys.join(", ")} not set. Postings are accepted and wait in the queue.
        </div>
      )}
    </>
  );
}

function App() {
  const { user, viewing, panelOpen, setPanelOpen, panelWidth } = useShared();
  return (
    <>
      <Header />
      <div className={`layout ${panelOpen ? "" : "folded"}`} style={{ "--side-w": `${panelWidth}px` } as React.CSSProperties}>
        {panelOpen ? (
          <SidePanel />
        ) : (
          <div className="rail">
            <button className="icon" onClick={() => setPanelOpen(true)} aria-label="Open the side panel" title="Open the panel">
              <Chevron direction="right" />
            </button>
          </div>
        )}
        {/* key: switching user or version reloads the page's data */}
        <Routes key={`${user.key}-${viewing ?? "live"}`}>
          <Route path="/" element={<Browse />} />
          <Route path="/labels/:id" element={<Decision />} />
          <Route path="/versions" element={<Versions />} />
          <Route path="/versions/:name" element={<Version />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="*" element={<p className="page">Page not found.</p>} />
        </Routes>
      </div>
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
