import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
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
  const isDraft = data.status === "draft";
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
      {isDraft ? <DraftGuide policy={data} /> : <PublishedNote policy={data} notify={setMessage} onChange={reload} />}
      {data.diff && <Changes policy={data} />}
      {isDraft && <DraftTools policy={data} onChange={reload} notify={setMessage} />}
      {isDraft ? <Editor policy={data} onSaved={reload} notify={setMessage} /> : <PolicyText policy={data} />}
    </div>
  );
}

// The three steps of a draft, and which are done.
function DraftGuide({ policy }: { policy: Policy }) {
  return (
    <ol className="steps-guide">
      <li className={policy.edited_by.length ? "done" : ""}>
        <b>1. Edit and save</b>
        Change the sections below, then Save. Editors and publishers can do this.
      </li>
      <li className={policy.tested ? "done" : ""}>
        <b>2. Test</b>
        Labels recent postings under this draft, without changing anything anyone sees, and lists what would change.
      </li>
      <li>
        <b>3. Publish</b>
        A publisher who did not edit the draft makes it live. Recent postings are then labeled again.
      </li>
    </ol>
  );
}

// A published version can't change, so every label traces to the exact policy it used.
function PublishedNote({ policy, notify, onChange }: { policy: Policy; notify: (m: string) => void; onChange: () => void }) {
  const { user } = useShared();
  const navigate = useNavigate();
  const { data: versions } = useLoad(api.versions, []);
  const next = `v${Math.max(0, ...(versions ?? []).map((v) => Number(v.name.replace(/\D/g, "")) || 0)) + 1}`;
  const { data: relabel } = useLoad(() => api.relabel(policy.name), [policy.name]);
  const pending = relabel ? (relabel.jobs.queued ?? 0) + (relabel.jobs.running ?? 0) : 0;
  return (
    <div className="note">
      <p>
        <b>{policy.name} is {policy.status === "live" ? "the live policy" : "no longer live"}.</b> Published versions can't
        be changed, so every label can be traced to the exact policy it used.
        {policy.status === "live" && " To change the policy, create a draft from it."}
      </p>
      {relabel && (
        <p className="muted">
          {relabel.labels} labels under {policy.name}
          {relabel.labels_without_a_model_call > 0 && <>, {relabel.labels_without_a_model_call} of them decided again in code at no cost</>}
          {pending > 0 && <>; {pending} postings are being labeled again</>}.
        </p>
      )}
      <div className="buttons">
        {policy.status === "live" && user.role !== "viewer" && (
          <button className="primary" onClick={() => api.createDraft(next).then((v) => navigate(`/versions/${v.name}`), (e) => notify(explain(e)))}>
            Create a draft from {policy.name} (as {next})
          </button>
        )}
        {policy.status === "retired" && (
          <button onClick={() => api.rollback(policy.name).then(() => { notify(`${policy.name} is live again.`); onChange(); }, (e) => notify(explain(e)))}>
            Make {policy.name} live again
          </button>
        )}
      </div>
      {policy.status === "live" && user.role === "viewer" && <p className="hint">Viewers can read policies. Switch to Eddie (editor) in "Acting as" to create a draft.</p>}
    </div>
  );
}

// "§5.text" -> "§5 Unverifiable employer: text"; header fields get plain names.
const HEADER: Record<string, string> = {
  "header.labels": "The label descriptions",
  "header.edge_cases": "The edge cases",
  "header.decision_rule": "The decision rule",
  screen_cut_off: "Jev's cut-off",
};
function describe(where: string, policy: Policy): string {
  if (HEADER[where]) return HEADER[where];
  const [code, field] = where.split(".");
  const title = policy.body.sections.find((s: any) => s.code === code)?.title ?? "";
  const fields: Record<string, string> = { text: "text", effect: "effect", screen: "Jev's question", examples: "examples", title: "title", red_flags: "red flags" };
  return `${code} ${title}${field ? `: ${fields[field] ?? field}` : ""}`;
}

function Changes({ policy }: { policy: Policy }) {
  const changes = policy.diff!.changes;
  return (
    <section className="card">
      <h3>What changed from {policy.diff!.against}</h3>
      {changes.length === 0 && <p className="muted small">Nothing yet.</p>}
      <ul className="changes">
        {changes.map((c) => (
          <li key={c.where + c.change}>
            {describe(c.where, policy)} {c.change}
            <span className="muted small">
              {c.models_see_it ? " · the models read this, so postings are labeled again by the model" : " · only code uses this, so labels are decided again at no cost"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Test and Publish. The buttons are there for every role: the API decides who may, and its answer
// is shown (that is the role demo).
function DraftTools({ policy, onChange, notify }: { policy: Policy; onChange: () => void; notify: (m: string) => void }) {
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
        <button onClick={() => act(() => api.startTest(policy.name), "Test started: recent postings are being labeled under this draft.")}>Test this draft</button>
        <button className="primary" onClick={() => act(() => api.publish(policy.name), "Published. Recent postings are being labeled again.")}>Publish</button>
      </div>
      {report && report.labeled + (report.jobs.queued ?? 0) + (report.jobs.running ?? 0) > 0 ? (
        <FlipReport report={report} />
      ) : (
        <p className="hint">Not tested yet. Publish needs a Test of the current draft.</p>
      )}
    </section>
  );
}

function FlipReport({ report }: { report: Report }) {
  const running = (report.jobs.queued ?? 0) + (report.jobs.running ?? 0);
  return (
    <div className="report" data-testid="flip-report">
      <p>
        <b>{report.passed ? "Test passed." : running ? `Test running: ${running} postings left.` : "Test not passed."}</b>{" "}
        {report.labeled} recent postings labeled under this draft (
        {report.mode === "redecide" ? "decided again in code, no model calls" : `${report.model_calls} model runs`}, $
        {report.cost_usd.toFixed(4)}). Compared with {report.compared_with}, {report.flips.length} would change
        {report.flips.length > 0 && <>; {report.flips_from_the_change} of them because of a section this draft changed</>}.
      </p>
      <ul className="invariants">
        {report.invariants.map((i) => (
          <li key={i.name} className={i.passed ? "ok" : "bad"}>{i.passed ? "✓" : "✗"} {i.name.replaceAll("_", " ")}</li>
        ))}
      </ul>
      {report.flips.length > 0 && (
        <table className="flips">
          <thead><tr><th>Job</th><th>Now</th><th>Under this draft</th><th>Why it changed</th></tr></thead>
          <tbody>
            {report.flips.map((f) => (
              <tr key={f.label_id}>
                <td><Link className="mono" to={`/labels/${f.label_id}`}>{f.job_id}</Link></td>
                <td><LabelBadge label={f.before.label} /> {f.before.sections.map((s) => <SectionTag key={s} code={s} />)}</td>
                <td><LabelBadge label={f.after.label} /> {f.after.sections.map((s) => <SectionTag key={s} code={s} />)}</td>
                <td className="muted small">{f.from_the_change ? "a section this draft changed" : "the model answered differently"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// A published policy, as text to read.
function PolicyText({ policy }: { policy: Policy }) {
  const body = policy.body;
  return (
    <section className="card policy-text">
      <h3>The policy</h3>
      <p><b>Edge cases</b></p>
      <ul>{body.header.edge_cases.map((e: string) => <li key={e}>{e}</li>)}</ul>
      {body.sections.map((s: any) => (
        <div className="sec-block" key={s.code} style={{ borderLeftColor: color(s.code) }}>
          <h4>
            <span style={{ color: color(s.code) }}>{s.code}</span> {s.title} <LabelBadge label={s.effect} />
          </h4>
          <p>{s.text}</p>
          <p className="muted">Jev's question: {s.screen.instructions}</p>
        </div>
      ))}
    </section>
  );
}

// The draft as a form, one folded block per section, so editing can't produce broken YAML.
function Editor({ policy, onSaved, notify }: { policy: Policy; onSaved: () => void; notify: (m: string) => void }) {
  const [body, setBody] = useState(() => structuredClone(policy.body));
  const { user } = useShared();
  useEffect(() => setBody(structuredClone(policy.body)), [policy]);

  const setSection = (i: number, update: (s: any) => void) =>
    setBody((b: any) => { const next = structuredClone(b); update(next.sections[i]); return next; });
  const save = () =>
    api.saveDraft(policy.name, body).then(
      () => { notify("Saved. Run Test again before publishing."); onSaved(); },
      (e) => notify(explain(e)),
    );

  return (
    <section className="card editor">
      <h3>Edit the draft (acting as {user.name})</h3>
      <div className="buttons"><button type="button" className="primary" onClick={save}>Save</button></div>
      <label className="block">Edge cases (one per line)
        <textarea rows={4} value={body.header.edge_cases.join("\n")}
          onChange={(e) => setBody((b: any) => ({ ...b, header: { ...b.header, edge_cases: e.target.value.split("\n").filter(Boolean) } }))} />
      </label>
      {body.sections.map((s: any, i: number) => (
        <details className="section-form" key={i} style={{ borderLeftColor: color(s.code) }} open={!s.title}>
          <summary>
            <span style={{ color: color(s.code) }}>{s.code}</span> {s.title || "New section"} <span className="muted">· {s.effect}</span>
          </summary>
          <div className="row">
            <input aria-label={`Section ${i + 1} code`} className="code" value={s.code} onChange={(e) => setSection(i, (x) => (x.code = e.target.value))} />
            <input aria-label={`${s.code} title`} className="grow" value={s.title} onChange={(e) => setSection(i, (x) => (x.title = e.target.value))} />
            <select aria-label={`${s.code} effect`} value={s.effect} onChange={(e) => setSection(i, (x) => (x.effect = e.target.value))}>
              <option value="VIOLATING">VIOLATING</option>
              <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
            </select>
          </div>
          <label className="block">Text<textarea rows={3} value={s.text} onChange={(e) => setSection(i, (x) => (x.text = e.target.value))} /></label>
          <label className="block">Jev's screen question<input value={s.screen.instructions} onChange={(e) => setSection(i, (x) => (x.screen.instructions = e.target.value))} /></label>
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
        </details>
      ))}
      <div className="buttons">
        <button type="button" onClick={() => setBody((b: any) => ({ ...b, sections: [...b.sections, newSection(b.sections.length + 1)] }))}>Add a section</button>
        <button type="button" className="primary" onClick={save}>Save</button>
      </div>
    </section>
  );
}

const newSection = (n: number) => ({
  code: `§${n}`, title: "", text: "", effect: "NEEDS_REVIEW",
  screen: { instructions: "", true: "", false: "" }, red_flags: [], examples: [{ text: "", matches: true }],
});
