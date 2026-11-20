import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, explain } from "../api";
import { ErrorNote, useLoad } from "../components/ui";

export default function Versions() {
  const { data, error } = useLoad(api.versions, []);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const navigate = useNavigate();

  return (
    <div className="page narrow">
      <h2>Policy versions</h2>
      <p className="muted">
        One version is live. A draft is edited, tested against recent postings in shadow, then published by someone
        who didn't edit it.
      </p>
      <ErrorNote error={error} />
      {data && (
        <div className="table-wrap">
          <table className="versions">
            <thead>
              <tr><th>Version</th><th>Status</th><th>From</th><th>Author</th><th className="hide-sm">Published</th></tr>
            </thead>
            <tbody>
              {data.map((v) => (
                <tr key={v.name}>
                  <td><Link className="mono" to={`/versions/${v.name}`}>{v.name}</Link></td>
                  <td><span className={`status ${v.status}`}>{v.status}</span>{v.status === "draft" && v.tested && <span className="muted small"> · tested</span>}</td>
                  <td className="mono">{v.parent ?? ""}</td>
                  <td>{v.author}</td>
                  <td className="hide-sm">{v.published_by ? `${v.published_by}, ${new Date(v.published_at!).toLocaleString()}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form
        className="new-draft"
        onSubmit={(e) => {
          e.preventDefault();
          api.createDraft(name.trim()).then(
            (v) => navigate(`/versions/${v.name}`),
            (err) => setMessage(explain(err)),
          );
        }}
      >
        <input aria-label="New draft name" placeholder="New draft name, e.g. v5" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" disabled={!name.trim()}>Create draft from the live version</button>
        {message && <p className="error" role="alert">{message}</p>}
      </form>
    </div>
  );
}
