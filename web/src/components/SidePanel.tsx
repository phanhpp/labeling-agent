import { Link, useNavigate } from "react-router";
import { useShared, type Tagged } from "../context";
import { USERS } from "../roles";

const tagWords = (v: Tagged) => (v.tags.length ? ` (${v.tags.join(", ")})` : "");

// The panel on the right: who you are, which policy version the pages show, and comparing the
// latest version with the previous one. It folds away; the header keeps showing who you are.
export function SidePanel() {
  const { user, setUser, versions, live, latest, previous, viewing, setViewing, setPanelOpen } = useShared();
  const navigate = useNavigate();
  const published = versions.filter((v) => v.status !== "draft");
  const shown = viewing ?? live;
  const shownVersion = versions.find((v) => v.name === shown);

  return (
    <aside className="side" aria-label="Side panel">
      <div className="buttons" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <b>Workspace</b>
        <button className="small" onClick={() => setPanelOpen(false)} aria-label="Fold the side panel">Fold ›</button>
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
        <p>
          The pages show labels under this version. Choosing one never changes what is live: only publishing does.
          {viewing && live && <> New postings are labeled under <b>{live}</b>.</>}
        </p>
      </section>

      <section>
        <span className="label-text">How labels changed</span>
        <button
          className="full"
          disabled={!previous || !latest}
          onClick={() => navigate(`/compare?from=${previous}&to=${latest}`)}
        >
          {previous && latest ? `Compare ${previous} → ${latest}` : "Compare previous → latest"}
        </button>
        <p>
          {previous && latest
            ? `Every posting labeled under both: its label under ${previous} (previous) next to ${latest} (latest).`
            : "Needs two published versions."}
        </p>
        <p><Link to="/versions">Manage versions →</Link></p>
      </section>
    </aside>
  );
}
