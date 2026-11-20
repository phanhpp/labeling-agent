import { useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, type LabelRow } from "../api";
import { PolicyMatch } from "../components/PolicyMatch";
import { ErrorNote, LabelBadge, color, useLoad } from "../components/ui";
import { useShared } from "../context";
import { DEFAULT_PER, LABELS, PAGE_SIZES, pageWindow, readFilters, toParams, toggle, type Filters } from "../lib/filters";
import { saveListContext } from "../lib/listContext";
import { field } from "../lib/words";

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const { sections, viewing } = useShared();
  const navigate = useNavigate();
  const { data, error } = useLoad(() => api.labels({ ...filters, version: filters.version ?? viewing ?? undefined }), [params.toString(), viewing]);
  const set = (next: Filters) => setParams(toParams(next));

  // Remember this page of the list, so the decision page can go back to it and step through it.
  useEffect(() => {
    if (data) saveListContext(`/?${params}`, data.items.map((row) => row.id));
  }, [data, params]);

  const per = filters.per ?? DEFAULT_PER;
  const page = filters.page ?? 1;
  const { offset } = pageWindow(filters);
  const pages = data ? Math.max(1, Math.ceil(data.total / per)) : 1;

  const filtersPanel = (
    <div className="filters" aria-label="Filters">
      <div className="group-head">Filter this list</div>
        <input
          className="search"
          placeholder="Search job id"
          aria-label="Search job id"
          defaultValue={filters.job_id ?? ""}
          onKeyDown={(e) => {
            if (e.key === "Enter") set({ ...filters, page: undefined, job_id: e.currentTarget.value.trim() || undefined });
          }}
        />
        <div className="label-text">Label</div>
        {LABELS.map((label) => (
          <button
            key={label}
            className={`chip ${filters.label === label ? "on" : ""}`}
            aria-pressed={filters.label === label}
            onClick={() => set(toggle(filters, "label", label))}
          >
            <LabelBadge label={label} />
            <span className="n">{data?.counts.label[label] ?? 0}</span>
          </button>
        ))}
        <div className="label-text">Policy section</div>
        {Object.entries(data?.counts.section ?? {}).map(([code, n]) => (
          <button
            key={code}
            className={`chip ${filters.section === code ? "on" : ""}`}
            aria-pressed={filters.section === code}
            onClick={() => set(toggle(filters, "section", code))}
          >
            <span><i className="dot" style={{ background: color(code) }} />{code} {sections[code] ?? ""}</span>
            <span className="n">{n}</span>
          </button>
        ))}
    </div>
  );

  return (
    <div className="page browse">
      <aside>{filtersPanel}</aside>

      <main>
        <ErrorNote error={error} />
        {data && (
          <>
            <div className="listbar">
              <span>
                {data.total === 0 ? "No postings" : `${offset + 1}–${Math.min(offset + per, data.total)} of ${data.total}`}
                {filters.label || filters.section || filters.job_id ? " matching the filters" : ""} · labels under {data.version} · newest first
              </span>
              <span className="spacer" />
              <Pager page={page} pages={pages} go={(p) => set({ ...filters, page: p })} />
              <label className="buttons">
                Rows per page
                <select
                  className="small"
                  aria-label="Rows per page"
                  value={per}
                  onChange={(e) => set({ ...filters, page: undefined, per: Number(e.target.value) })}
                >
                  {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            </div>
            <div className="table-wrap">
              <table className="labels">
                <thead>
                  <tr>
                    <th>Label</th>
                    <th className="hide-sm job-col">Job</th>
                    <th className="col-posting">Posting and its evidence</th>
                    <th className="col-match hide-sm">Policy match</th>
                    <th className="hide-sm conf-col" title="How sure the model said it was, from 0 to 1 (its own estimate)">Confidence</th>
                    <th className="hide-sm col-why">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.id} onClick={() => navigate(`/labels/${row.id}`)}>
                      <td>
                        <LabelBadge label={row.label} />
                        {row.decision && <div className="analyst">Analyst: {row.decision.replace("_", " ").toLowerCase()}</div>}
                      </td>
                      <td className="mono job hide-sm">{row.job_id}</td>
                      <td className="title">
                        <Link to={`/labels/${row.id}`} onClick={(e) => e.stopPropagation()}>{row.title}</Link>
                        <Preview row={row} />
                        <div className="show-sm match-inline"><PolicyMatch match={row.policy_match} titles={sections} labelId={row.id} reasons={row.reason_codes} /></div>
                      </td>
                      <td className="hide-sm"><PolicyMatch match={row.policy_match} titles={sections} labelId={row.id} reasons={row.reason_codes} /></td>
                      <td className="conf hide-sm">{row.confidence.toFixed(2)}</td>
                      <td className="why hide-sm"><div>{row.rationale}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty-note">No labels match these filters.</p>}
            </div>
            <div className="pager"><Pager page={page} pages={pages} go={(p) => set({ ...filters, page: p })} /></div>
          </>
        )}
      </main>
    </div>
  );
}

function Pager({ page, pages, go }: { page: number; pages: number; go: (page: number) => void }) {
  return (
    <nav className="buttons" aria-label="Pages">
      <span>Page {page} of {pages}</span>
      <button className="small" disabled={page <= 1} onClick={() => go(page - 1)}>← Previous</button>
      <button className="small" disabled={page >= pages} onClick={() => go(page + 1)}>Next →</button>
    </nav>
  );
}

// One line of evidence under the title: the main quote in its section's colour, or the empty fields
// the label rests on.
function Preview({ row }: { row: LabelRow }) {
  const p = row.evidence_preview;
  if (!p) return null;
  return (
    <div className="preview" data-testid="evidence-preview">
      {p.text ? (
        <mark style={{ "--c": color(p.section) } as React.CSSProperties}>“{p.text}”</mark>
      ) : (
        <span className="missing">{p.section}: empty {p.missing!.map(field).join(", ")}</span>
      )}
    </div>
  );
}
