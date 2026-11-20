import { useRef } from "react";
import { Link, useNavigate } from "react-router";
import { useShared, type Tagged } from "../context";
import { USERS } from "../roles";
import { dragEdge } from "../lib/drag";
import { api } from "../api";
import { Fold } from "./Fold";
import { LiveRunSection } from "./LiveRun";
import { PanelToggle } from "./PanelToggle";
import { useLoad } from "./ui";
import { RelabelProgress, useRelabel } from "./Relabel";

const tagWords = (v: Tagged) => (v.tags.length ? ` (${v.tags.join(", ")})` : "");

// The Workspace panel on the right: who you are, which policy version the pages show, and comparing
// the latest version with the previous one. It hides to a thin strip (the toggle stays in the same
// place, top right), and its left edge can be dragged to resize it.
export function SidePanel() {
  const { user, setUser, versions, live, latest, previous, viewing, setViewing, setPanelOpen, setPanelWidth } = useShared();
  const navigate = useNavigate();
  const box = useRef<HTMLElement>(null);
  const published = versions.filter((v) => v.status !== "draft");
  const shown = viewing ?? live;
  const shownVersion = versions.find((v) => v.name === shown);
  const relabel = useRelabel(live); // after a publish, watch the re-label from any page
  const { data: health } = useLoad(api.health, []);

  // the panel's right edge is the window's; dragging its left edge sets the width
  const startResize = (e: React.PointerEvent) => {
    const right = box.current?.getBoundingClientRect().right ?? window.innerWidth;
    dragEdge(e, (x) => right - x, setPanelWidth);
  };

  return (
    <aside className="side" aria-label="Side panel" ref={box}>
      <div className="side-head">
        <div className="group-head" style={{ margin: 0 }}>Workspace <span className="muted small">(every page)</span></div>
        <PanelToggle panel="workspace" side="right" open onToggle={() => setPanelOpen(false)} />
      </div>

      <section>
        <label>
          <span className="label-text">You are</span>
          <select aria-label="Acting as" value={user.key} onChange={(e) => setUser(USERS.find((u) => u.key === e.target.value)!)}>
            {USERS.map((u) => (
              <option key={u.key} value={u.key}>{u.name}, {u.role}</option>
            ))}
          </select>
        </label>
        <p>{user.name} {user.can}.</p>
      </section>

      <section>
        <label>
          <span className="label-text">Policy shown</span>
          <select aria-label="Policy shown" value={shown ?? ""} onChange={(e) => setViewing(e.target.value === live ? null : e.target.value)}>
            {published.map((v) => (
              <option key={v.name} value={v.name}>{v.name}{tagWords(v)}</option>
            ))}
          </select>
        </label>
        {shownVersion && (
          <div className="tags">
            {shownVersion.tags.map((t) => <span key={t} className={`tag ${t}`}>{t}</span>)}
          </div>
        )}
        <p>Choosing a version changes what the pages show, never what is live: only publishing does.</p>
      </section>

      <Fold id="compare" title="How labels changed" hint={relabel?.relabel?.waiting ? "re-labeling…" : undefined}>
        <button className="full" disabled={!previous || !latest} onClick={() => navigate(`/compare?from=${previous}&to=${latest}`)}>
          {previous && latest ? `Compare ${previous} → ${latest}` : "Compare previous → latest"}
        </button>
        <p>
          {previous && latest ? `Each posting's label under ${previous} (previous) next to ${latest} (latest).` : "Needs two published versions."}{" "}
          <Link to="/versions">Manage versions</Link>
        </p>
        <RelabelProgress relabel={relabel} compact />
      </Fold>

      {health?.demo?.enabled && <LiveRunSection health={health} />}

      <div className="resizer" role="separator" aria-orientation="vertical" aria-label="Resize the side panel" onPointerDown={startResize} title="Drag to resize" />
    </aside>
  );
}
