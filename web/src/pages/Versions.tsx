import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, explain } from "../api";
import { ErrorNote, useLoad } from "../components/ui";
import { useShared } from "../context";

// "bootstrap" is the app loading policies/v1.yaml at startup, not a person.
const person = (name: string | null) => (name === "bootstrap" ? "loaded at startup" : name ?? "");

export default function Versions() {
  const { data, error } = useLoad(api.versions, []);
  const { user } = useShared();
  const [message, setMessage] = useState("");
  const navigate = useNavigate();
  const live = data?.find((v) => v.status === "live");
  const next = `v${Math.max(0, ...(data ?? []).map((v) => Number(v.name.replace(/\D/g, "")) || 0)) + 1}`;

  return (
    <div className="page">
      <h1 className="page-title">Policy versions</h1>
      <p className="muted">
        One version is live and labels every new posting. To change the policy, create a draft, edit and Test it on
        recent postings; then a publisher who didn't edit it publishes it.
      </p>
      <ErrorNote error={error} />
      {message && <p className="error" role="alert">{message}</p>}
      {data && (
        <>
          <div className="buttons" style={{ margin: "12px 0 16px" }}>
            {user.role !== "viewer" && live && (
              <button
                className="primary"
                onClick={() => api.createDraft(next).then((v) => navigate(`/versions/${v.name}`), (err) => setMessage(explain(err)))}
              >
                Create a draft from {live.name} (as {next})
              </button>
            )}
            {user.role === "viewer" && <span className="hint">Viewers can read policies. Editors and publishers can create drafts.</span>}
          </div>
          <div className="table-wrap">
            <table className="versions">
              <thead>
                <tr><th>Version</th><th>Status</th><th>Made from</th><th>Written</th><th className="hide-sm">Published</th></tr>
              </thead>
              <tbody>
                {data.map((v) => (
                  <tr key={v.name}>
                    <td><Link className="mono" to={`/versions/${v.name}`}>{v.name}</Link></td>
                    <td>
                      <span className={`status ${v.status}`}>{v.status}</span>
                      {v.status === "draft" && <span className="muted small"> · {v.tested ? "tested" : "not tested yet"}</span>}
                    </td>
                    <td className="mono">{v.parent ?? ""}</td>
                    <td>{person(v.author)}</td>
                    <td className="hide-sm">{v.published_by ? `${person(v.published_by)}, ${new Date(v.published_at!).toLocaleString()}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
