import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api } from "../api";
import { ErrorNote, LabelBadge, SectionTag, useLoad } from "../components/ui";

const PER = 25;

// Every posting labeled under two versions, its label under each side by side. By default only the
// postings whose label or sections changed.
export default function Compare() {
  const [params] = useSearchParams();
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const navigate = useNavigate();
  const { data, error } = useLoad(() => api.compare(from, to), [from, to]);
  const [onlyChanged, setOnlyChanged] = useState(true);
  const [page, setPage] = useState(1);

  if (!from || !to) return <div className="page"><p>Choose two versions in the side panel.</p></div>;
  if (error) return <div className="page"><ErrorNote error={error} /></div>;
  if (!data) return <div className="page muted">Loading…</div>;

  const rows = onlyChanged ? data.rows.filter((r) => r.changed) : data.rows;
  const pages = Math.max(1, Math.ceil(rows.length / PER));
  const shown = rows.slice((page - 1) * PER, page * PER);

  return (
    <div className="page">
      <h1 className="page-title">How labels changed from {from} to {to}</h1>
      <p className="muted">
        {data.postings} postings are labeled under both. <b>{data.changed}</b> changed label or sections.
        {data.changed > 0 && (
          <>
            {" "}{data.from_the_change} of those involve a section that differs between {from} and {to}; the others are
            Claude answering differently when asked again.
          </>
        )}
      </p>
      <div className="listbar">
        <label className="switch">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => { setOnlyChanged(e.target.checked); setPage(1); }} />
          Only postings that changed
        </label>
        <span className="spacer" />
        <span>Page {page} of {pages}</span>
        <button className="small" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Previous</button>
        <button className="small" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
      </div>
      <div className="table-wrap">
        <table className="labels" data-testid="compare">
          <thead>
            <tr>
              <th className="hide-sm">Job</th>
              <th className="col-posting">Posting</th>
              <th>Label under {from}</th>
              <th>Label under {to}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.posting_id} onClick={() => navigate(`/labels/${r.new.label_id}`)}>
                <td className="mono job hide-sm">{r.job_id}</td>
                <td className="title"><Link to={`/labels/${r.new.label_id}`} onClick={(e) => e.stopPropagation()}>{r.title}</Link></td>
                <td><LabelBadge label={r.old.label} /> {r.old.sections.map((s) => <SectionTag key={s} code={s} />)}</td>
                <td><LabelBadge label={r.new.label} /> {r.new.sections.map((s) => <SectionTag key={s} code={s} />)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <p className="empty-note">No postings changed.</p>}
      </div>
    </div>
  );
}
