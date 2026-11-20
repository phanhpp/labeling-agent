import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, explain, type Policy, type Report } from "../api";
import { ErrorNote, LabelBadge, SectionTag, color, useLoad } from "../components/ui";
import { useShared } from "../context";

export default function Version() {
  const { name = "" } = useParams();
  // Kept here, not in the panels: publishing turns the draft panel into the live one.
  const [message, setMessage] = useState("");
  const { data, error, reload } = useLoad(async () => {
    const plain = await api.version(name);
    return plain.parent ? api.version(name, plain.parent) : plain;
  }, [name]);
  if (error) return <div className="page"><ErrorNote error={error} /></div>;
  if (!data) return <div className="page muted">Loading…</div>;
  return (
    <div className="page narrow">
      <div className="crumb"><Link to="/versions">Versions</Link> / <span className="mono">{data.name}</span></div>
      <h2>
        {data.name} <span className={`status ${data.status}`}>{data.status}</span>
      </h2>
      <p className="muted">
        From {data.parent ?? "the start"} · author {data.author}
        {data.edited_by.length > 0 && <> · edited by {data.edited_by.join(", ")}</>}
        {data.published_by && <> · published by {data.published_by}</>}
      </p>
      {message && <p className="message" role="status">{message}</p>}
      {data.diff && <Changes policy={data} />}
      {data.status === "draft" ? (
        <DraftTools policy={data} onChange={reload} notify={setMessage} />
      ) : (
        <Published policy={data} onChange={reload} notify={setMessage} />
      )}
      <Editor policy={data} onSaved={reload} />
    </div>
  );
}

function Changes({ policy }: { policy: Policy }) {
  const changes = policy.diff!.changes;
  return (
    <section className="card">
      <h3>Changes from {policy.diff!.against}</h3>
      {changes.length === 0 && <p className="muted small">None yet.</p>}
      <ul className="changes">
        {changes.map((c) => (
          <li key={c.where + c.change}>
            <span className="mono">{c.where}</span> {c.change}
            <span className="muted small">{c.models_see_it ? " · the models see this" : " · code only: re-decided at $0"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Test and Publish for a draft. The buttons are there for every role: the API decides who may, and
// its answer is shown (that is the role demo).
type Panel = { policy: Policy; onChange: () => void; notify: (message: string) => void };

function DraftTools({ policy, onChange, notify }: Panel) {
  const [report, setReport] = useState<Report | null>(null);
  const [polls, setPolls] = useState(0);

  useEffect(() => {
    api.report(policy.name).then(setReport, () => setReport(null));
  }, [policy.name, polls]);
  useEffect(() => {
    const running = report && (report.jobs.queued || report.jobs.running);
    if (!running) return;
    const timer = setTimeout(() => setPolls((n) => n + 1), 1000);
    return () => clearTimeout(timer);
  }, [report]);

  const act = (action: () => Promise<unknown>, done: string) =>
    action().then(
      () => { notify(done); setPolls((n) => n + 1); onChange(); },
      (err) => notify(explain(err)),
    );

  return (
    <section className="card">
      <h3>Test and publish</h3>
      <div className="buttons">
        <button onClick={() => act(() => api.startTest(policy.name), "Test started: recent postings are being labeled under this draft.")}>Test</button>
        <button className="primary" onClick={() => act(() => api.publish(policy.name), "Published. Recent postings are being labeled again.")}>Publish</button>
      </div>
      {report && report.labeled + (report.jobs.queued ?? 0) + (report.jobs.running ?? 0) > 0 && <FlipReport report={report} />}
    </section>
  );
}

function FlipReport({ report }: { report: Report }) {
  const running = (report.jobs.queued ?? 0) + (report.jobs.running ?? 0);
  return (
    <div className="report" data-testid="flip-report">
      <p>
        <b>{report.passed ? "Test passed." : running ? `Test running: ${running} postings left.` : "Test not passed."}</b>{" "}
        {report.labeled} postings labeled ({report.mode === "redecide" ? "decided again in code, no model calls" : `${report.model_calls} model runs`}),
        ${report.cost_usd.toFixed(4)}. Compared with {report.compared_with}: {report.flips.length} changed,{" "}
        {report.flips_from_the_change} involving a changed section.
      </p>
      <ul className="invariants">
        {report.invariants.map((i) => (
          <li key={i.name} className={i.passed ? "ok" : "bad"}>{i.passed ? "✓" : "✗"} {i.name.replaceAll("_", " ")}</li>
        ))}
      </ul>
      {report.flips.length > 0 && (
        <table className="flips">
          <thead><tr><th>Job</th><th>Before</th><th>After</th><th>Why</th></tr></thead>
          <tbody>
            {report.flips.map((f) => (
              <tr key={f.label_id}>
                <td><Link className="mono" to={`/labels/${f.label_id}`}>{f.job_id}</Link></td>
                <td><LabelBadge label={f.before.label} /> {f.before.sections.map((s) => <SectionTag key={s} code={s} />)}</td>
                <td><LabelBadge label={f.after.label} /> {f.after.sections.map((s) => <SectionTag key={s} code={s} />)}</td>
                <td className="muted small">{f.from_the_change ? "the change" : "model variation"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Published({ policy, onChange, notify }: Panel) {
  const { data } = useLoad(() => api.relabel(policy.name), [policy.name]);
  const pending = data ? (data.jobs.queued ?? 0) + (data.jobs.running ?? 0) : 0;
  return (
    <section className="card">
      <h3>Labels under {policy.name}</h3>
      {data && (
        <p>
          {data.labels} labels, {data.labels_without_a_model_call} decided in code without a model call, ${data.cost_usd.toFixed(4)}
          {pending > 0 && <>; re-label in progress, {pending} left</>}.
        </p>
      )}
      {policy.status === "retired" && (
        <button onClick={() => api.rollback(policy.name).then(() => { notify(`${policy.name} is live again.`); onChange(); }, (e) => notify(explain(e)))}>
          Make {policy.name} live again
        </button>
      )}
    </section>
  );
}

// The policy as a form, one block per section, so editing can't produce broken YAML. Published
// versions are shown read-only.
function Editor({ policy, onSaved }: { policy: Policy; onSaved: () => void }) {
  const [body, setBody] = useState(() => structuredClone(policy.body));
  const [message, setMessage] = useState("");
  const { user } = useShared();
  const readOnly = policy.status !== "draft";
  useEffect(() => setBody(structuredClone(policy.body)), [policy]);

  const setSection = (i: number, update: (s: any) => void) =>
    setBody((b: any) => { const next = structuredClone(b); update(next.sections[i]); return next; });

  return (
    <section className="card editor">
      <h3>{readOnly ? "Policy" : `Edit draft (as ${user.name})`}</h3>
      <fieldset disabled={readOnly}>
        <label className="block">Edge cases (one per line)
          <textarea rows={4} value={body.header.edge_cases.join("\n")}
            onChange={(e) => setBody((b: any) => ({ ...b, header: { ...b.header, edge_cases: e.target.value.split("\n").filter(Boolean) } }))} />
        </label>
        {body.sections.map((s: any, i: number) => (
          <div className="section-form" key={i} style={{ borderLeftColor: color(s.code) }}>
            <div className="row">
              <input aria-label={`Section ${i + 1} code`} className="code" value={s.code} onChange={(e) => setSection(i, (x) => (x.code = e.target.value))} />
              <input aria-label={`${s.code} title`} className="grow" value={s.title} onChange={(e) => setSection(i, (x) => (x.title = e.target.value))} />
              <select aria-label={`${s.code} effect`} value={s.effect} onChange={(e) => setSection(i, (x) => (x.effect = e.target.value))}>
                <option value="VIOLATING">VIOLATING</option>
                <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
              </select>
            </div>
            <label className="block">Text<textarea rows={3} value={s.text} onChange={(e) => setSection(i, (x) => (x.text = e.target.value))} /></label>
            <label className="block">Screen question<input value={s.screen.instructions} onChange={(e) => setSection(i, (x) => (x.screen.instructions = e.target.value))} /></label>
            <div className="row">
              <label className="block grow">Counts as yes<textarea rows={2} value={s.screen.true} onChange={(e) => setSection(i, (x) => (x.screen.true = e.target.value))} /></label>
              <label className="block grow">Counts as no<textarea rows={2} value={s.screen.false} onChange={(e) => setSection(i, (x) => (x.screen.false = e.target.value))} /></label>
            </div>
            <div className="examples">
              {s.examples.map((ex: any, j: number) => (
                <div className="row" key={j}>
                  <select aria-label="Example matches" value={String(ex.matches)} onChange={(e) => setSection(i, (x) => (x.examples[j].matches = e.target.value === "true"))}>
                    <option value="true">matches</option>
                    <option value="false">doesn't match</option>
                  </select>
                  <input className="grow" aria-label="Example text" value={ex.text} onChange={(e) => setSection(i, (x) => (x.examples[j].text = e.target.value))} />
                </div>
              ))}
            </div>
          </div>
        ))}
        {!readOnly && (
          <div className="buttons">
            <button type="button" onClick={() => setBody((b: any) => ({ ...b, sections: [...b.sections, newSection(b.sections.length + 1)] }))}>Add section</button>
            <button type="button" className="primary" onClick={() => api.saveDraft(policy.name, body).then(
              () => { setMessage("Saved. Run Test again before publishing."); onSaved(); },
              (e) => setMessage(explain(e)),
            )}>Save</button>
          </div>
        )}
      </fieldset>
      {message && <p className="message" role="status">{message}</p>}
    </section>
  );
}

const newSection = (n: number) => ({
  code: `§${n}`, title: "", text: "", effect: "NEEDS_REVIEW",
  screen: { instructions: "", true: "", false: "" }, red_flags: [], examples: [{ text: "", matches: true }],
});
