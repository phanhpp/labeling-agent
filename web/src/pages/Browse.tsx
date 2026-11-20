import { Link, useSearchParams } from "react-router";
import { api } from "../api";
import { ErrorNote, LabelBadge, SectionTag, color, useLoad } from "../components/ui";
import { useShared } from "../context";
import { LABELS, readFilters, toParams, toggle, type Filters } from "../lib/filters";

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const { sections } = useShared();
  const { data, error } = useLoad(() => api.labels(filters), [params.toString()]);
  // The chip counts come from the API for the whole version, so they don't change while filtering.
  const set = (next: Filters) => setParams(toParams(next));

  return (
    <div className="page browse">
      <aside className="filters">
        <input
          className="search"
          placeholder="Search job id"
          aria-label="Search job id"
          defaultValue={filters.job_id ?? ""}
          onKeyDown={(e) => {
            if (e.key === "Enter") set({ ...filters, job_id: e.currentTarget.value.trim() || undefined });
          }}
        />
        <h4>Label</h4>
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
        <h4>Section</h4>
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
      </aside>

      <main>
        <ErrorNote error={error} />
        {data && (
          <>
            <p className="count">
              {data.total} {data.total === 1 ? "posting" : "postings"} under {data.version}
              {filters.label || filters.section || filters.job_id ? " matching the filters" : ""}, newest first
            </p>
            <div className="table-wrap">
              <table className="labels">
                <thead>
                  <tr><th>Label</th><th>Job</th><th>Title</th><th>Sections</th><th className="hide-sm" title="How sure the model said it was, from 0 to 1 (its own estimate)">Confidence</th><th className="hide-sm">Why</th></tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <LabelBadge label={row.label} />
                        {row.decision && <div className="analyst">Analyst: {row.decision.replace("_", " ").toLowerCase()}</div>}
                      </td>
                      <td className="mono">{row.job_id}</td>
                      <td className="title"><Link to={`/labels/${row.id}`}>{row.title}</Link></td>
                      <td>{row.sections.map((s) => <SectionTag key={s} code={s} title={sections[s]} />)}</td>
                      <td className="conf hide-sm">{row.confidence.toFixed(2)}</td>
                      <td className="why hide-sm">{row.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty-note">No labels match these filters.</p>}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
