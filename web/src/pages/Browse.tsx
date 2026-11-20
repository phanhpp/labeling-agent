import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, type LabelRow } from "../api";
import { PanelToggle, usePanelShortcut } from "../components/PanelToggle";
import { DatasetCell } from "../components/Dataset";
import { useBatch } from "../components/LiveRun";
import { PolicyMatch } from "../components/PolicyMatch";
import { ErrorNote, LabelBadge, color, useLoad } from "../components/ui";
import { store, stored, useShared } from "../context";
import { DEFAULT_PER, LABELS, PAGE_SIZES, pageWindow, readFilters, sectionCodes, toParams, toggle, type Filters } from "../lib/filters";
import { dragEdge } from "../lib/drag";
import { saveListContext } from "../lib/listContext";
import { field, plural } from "../lib/words";

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const { sections, viewing, compareDataset, setCompareDataset } = useShared();
  const { data: health } = useLoad(api.health, []);
  const navigate = useNavigate();
  const { data, error, reload } = useLoad(
    () => api.labels({ ...filters, version: filters.version ?? viewing ?? undefined }, compareDataset),
    [params.toString(), viewing, compareDataset],
  );
  // A live-demo run: its postings only, and the list fills in while they are being labeled.
  const run = useBatch(filters.batch ?? null);
  const labeledSoFar = run?.labeled;
  useEffect(() => {
    if (labeledSoFar !== undefined) reload();
  }, [labeledSoFar]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (next: Filters) => setParams(toParams(next));

  // Remember this page of the list, so the decision page can go back to it and step through it.
  useEffect(() => {
    if (data) saveListContext(`/?${params}`, data.items.map((row) => row.id));
  }, [data, params]);

  const per = filters.per ?? DEFAULT_PER;
  const page = filters.page ?? 1;
  const { offset } = pageWindow(filters);
  const pages = data ? Math.max(1, Math.ceil(data.total / per)) : 1;

  // The filters hide like a sidebar (⌘B); the list then takes the whole width. On a phone they start hidden.
  const [filtersOpen, setFiltersOpen] = useState(() => stored("filters", window.innerWidth > 900 ? "open" : "hidden") === "open");
  const toggleFilters = () => {
    store("filters", filtersOpen ? "hidden" : "open");
    setFiltersOpen(!filtersOpen);
  };
  usePanelShortcut("filters", toggleFilters);
  // Drag the filters' right edge to resize them (180 to 420 px), like the workspace.
  const [filtersWidth, setFiltersWidthState] = useState(() => Number(stored("filters-width", "240")) || 240);
  const setFiltersWidth = (px: number) => {
    const width = Math.round(Math.min(420, Math.max(180, px)));
    store("filters-width", String(width));
    setFiltersWidthState(width);
  };
  const filtersBox = useRef<HTMLElement>(null);
  const filtering = !!(filters.label || filters.section || filters.job_id);

  const filtersPanel = (
    <div className="filters" aria-label="Filters">
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
        {/* every section of the policy shown, also those no posting matches (0) */}
        {sectionCodes(sections, data?.counts.section ?? {}).map(([code, n]) => (
          <button
            key={code}
            className={`chip ${filters.section === code ? "on" : ""} ${n === 0 ? "zero" : ""}`}
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
    <div className={`page browse ${filtersOpen ? "" : "filters-hidden"}`} style={{ "--filters-w": `${filtersWidth}px` } as React.CSSProperties}>
      <aside className="filters-col" ref={filtersBox}>
        <div className="filters-head">
          {/* a dot on the hidden toggle says the list is filtered */}
          <PanelToggle panel="filters" side="left" open={filtersOpen} onToggle={toggleFilters} dot={!filtersOpen && filtering} />
          {filtersOpen && <span className="group-head">Filter this list</span>}
        </div>
        {filtersOpen && filtersPanel}
        {filtersOpen && (
          <div
            className="resizer resizer-right"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the filters"
            title="Drag to resize"
            onPointerDown={(e) => {
              const left = filtersBox.current?.getBoundingClientRect().left ?? 0;
              dragEdge(e, (x) => x - left, setFiltersWidth);
            }}
          />
        )}
      </aside>

      <main>
        <ErrorNote error={error} />
        {data && (
          <>
            {filters.batch && (
              <div className="scope" data-testid="run-scope">
                <b>Run {filters.batch} only</b>
                {run && <span>{run.waiting ? `${run.labeled} of ${run.postings} labeled, the list fills in as they finish…` : `all ${run.postings} labeled`}</span>}
                <span className="spacer" />
                <button className="small" onClick={() => set({ ...filters, batch: undefined, page: undefined })}>Show all postings</button>
              </div>
            )}
            {compareDataset && data.dataset && (
              <div className="scope dataset" data-testid="dataset-summary">
                <span>
                  {data.dataset.with_dataset === 0 ? (
                    "None of these postings came from the dataset, so there is no dataset answer to compare."
                  ) : (
                    <>
                      <b>Against the dataset's answer</b> ({plural(data.dataset.with_dataset, "posting")}): of the{" "}
                      <b>{data.dataset.fraud} fraud</b>, we flagged {data.dataset.caught} and missed{" "}
                      {data.dataset.fraud - data.dataset.caught}. Of the{" "}
                      <b>{data.dataset.with_dataset - data.dataset.fraud} legitimate</b>, we wrongly flagged{" "}
                      {data.dataset.false_alarms}. <span className="muted">Flagged means VIOLATING or sent to review.</span>
                    </>
                  )}
                </span>
                <span className="spacer" />
                <label className="switch">
                  <input type="checkbox" checked={!!filters.disagree} onChange={(e) => set({ ...filters, page: undefined, disagree: e.target.checked || undefined })} />
                  Only where they disagree
                </label>
              </div>
            )}
            <div className="listbar">
              <span>
                {data.total === 0 ? "No postings" : `${offset + 1}–${Math.min(offset + per, data.total)} of ${data.total}`}
                {filters.label || filters.section || filters.job_id ? " matching the filters" : ""} · labels under {data.version} · newest postings first
              </span>
              {health?.demo?.enabled && (
                <label className="switch" title="Demo: the dataset's own answer next to ours. Off, the list looks like production.">
                  <input type="checkbox" checked={compareDataset} onChange={(e) => setCompareDataset(e.target.checked)} />
                  Compare with the dataset's label
                </label>
              )}
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
                    {compareDataset && <th className="dataset-col">Dataset says</th>}
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
                      {compareDataset && <td className="dataset-cell"><DatasetCell label={row.label} dataset={row.dataset ?? null} /></td>}
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
