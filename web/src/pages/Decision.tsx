import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, explain, type Detail, type Steps } from "../api";
import { ErrorNote, LabelBadge, SectionTag, color, useLoad } from "../components/ui";
import { useShared } from "../context";
import { segments, spansFor } from "../lib/highlight";
import { durations, summary } from "../lib/steps";

const FIELDS: [string, string][] = [
  ["company_profile", "Company profile"],
  ["description", "Description"],
  ["requirements", "Requirements"],
  ["benefits", "Benefits"],
  ["salary_range", "Salary"],
];

export default function Decision() {
  const { id = "" } = useParams();
  const { data, error, reload } = useLoad(() => api.label(id), [id]);
  if (error) return <div className="page"><ErrorNote error={error} /></div>;
  if (!data) return <div className="page muted">Loading…</div>;
  return (
    <div className="page decision">
      <main>
        <div className="crumb"><Link to="/">Labels</Link> / <span className="mono">{data.job_id}</span></div>
        <Posting label={data} />
      </main>
      <aside className="rail">
        <Verdict label={data} onDecided={reload} />
        <Findings label={data} />
        <Guardrails label={data} />
        <Timeline postingId={data.posting_id} />
        <History label={data} />
      </aside>
    </div>
  );
}

// The posting as the models saw it (cleaned), as plain text. Verified quotes are highlighted from
// their stored positions, in their section's colour. React renders text, never HTML.
function Posting({ label }: { label: Detail }) {
  const c = label.cleaned;
  const meta = [c.location, c.employment_type, c.industry].filter(Boolean).join(" · ");
  return (
    <article className="doc">
      <h1>{c.title}</h1>
      <div className="meta">
        {meta && <>{meta} · </>}job <span className="mono">{label.job_id}</span> · client {label.client_id}
        {c.has_company_logo === "1" ? " · logo shown" : " · no logo"}
      </div>
      {FIELDS.map(([field, name]) => (
        <section className="field" key={field}>
          <h5>{name}</h5>
          {c[field] ? (
            <p>
              {segments(c[field], spansFor(field, label.findings)).map((seg, i) =>
                seg.section ? (
                  <mark key={i} data-section={seg.section} style={{ "--c": color(seg.section) } as React.CSSProperties}>
                    {seg.text}
                    <sup>{seg.section}</sup>
                  </mark>
                ) : (
                  <span key={i}>{seg.text}</span>
                ),
              )}
            </p>
          ) : (
            <span className="empty">Empty</span>
          )}
        </section>
      ))}
    </article>
  );
}

function Verdict({ label, onDecided }: { label: Detail; onDecided: () => void }) {
  const { user, sections } = useShared();
  const decision = label.decisions[0];
  return (
    <section className="card">
      <h3>Label</h3>
      <div className="verdict">
        <LabelBadge label={label.label} />
        {label.policy_sections.map((s) => <SectionTag key={s} code={s} title={sections[s]} />)}
        <span className="muted">confidence {label.confidence.toFixed(2)} · {label.policy_version}</span>
      </div>
      <p className="rationale">{label.rationale}</p>
      {label.reason_codes.length > 0 && <p className="codes">{label.reason_codes.map((r) => <code key={r}>{r}</code>)}</p>}
      {decision && (
        <div className="final" data-testid="analyst-decision">
          <b>Analyst decision: {decision.label.replace("_", " ").toLowerCase()}</b> (final) · {decision.analyst}
          {decision.note && <div>{decision.note}</div>}
        </div>
      )}
      {user.role !== "viewer" && <DecideForm labelId={label.id} onDecided={onDecided} />}
    </section>
  );
}

function DecideForm({ labelId, onDecided }: { labelId: number; onDecided: () => void }) {
  const [choice, setChoice] = useState("NEEDS_REVIEW");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  return (
    <form
      className="decide"
      onSubmit={(e) => {
        e.preventDefault();
        api.decide(labelId, choice, note).then(
          () => { setMessage("Decision recorded."); setNote(""); onDecided(); },
          (err) => setMessage(explain(err)),
        );
      }}
    >
      <select aria-label="Your decision" value={choice} onChange={(e) => setChoice(e.target.value)}>
        <option value="VIOLATING">Violating</option>
        <option value="NEEDS_REVIEW">Needs review</option>
        <option value="ALLOWED">Allowed</option>
      </select>
      <input aria-label="Note" placeholder="Note for the record" value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="submit">Record decision</button>
      {message && <p className="muted small">{message}</p>}
    </form>
  );
}

function Findings({ label }: { label: Detail }) {
  const { sections } = useShared();
  return (
    <section className="card">
      <h3>Findings by section</h3>
      {label.findings.length === 0 && <p className="muted small">No model answered: {label.reason_codes.join(", ") || "see the steps"}.</p>}
      {label.findings.map((f) => (
        <div className={`finding ${f.status}`} key={f.section}>
          <span className="code" style={{ color: color(f.section) }}>{f.section}</span>
          <span>{sections[f.section] ?? ""}</span>
          <span className="st">{f.status.replace("_", " ")}</span>
          <span className="r">
            {f.reasoning}
            {f.missing_fields.length > 0 && <> Missing: {f.missing_fields.join(", ")}.</>}
            {f.dropped_quotes.length > 0 && <> Dropped quotes (not found in the posting): {f.dropped_quotes.map((q) => `"${q}"`).join(", ")}.</>}
          </span>
        </div>
      ))}
    </section>
  );
}

function Guardrails({ label }: { label: Detail }) {
  const s = label.screen ?? {};
  const dropped = label.findings.reduce((n, f) => n + f.dropped_quotes.length, 0);
  const verified = label.findings.reduce((n, f) => n + f.quotes.length, 0);
  const injection = s.injection_flag
    ? `suspected${s.regex_hits?.length ? `: "${s.regex_hits[0]}"` : s.injection != null ? `, score ${s.injection.toFixed(2)}` : ""}`
    : s.injection != null ? `none (score ${s.injection.toFixed(2)})` : "none found";
  const screen = s.used ? `${s.used}${s.cleared ? ", cleared" : ""}${(s.reason_codes ?? []).length ? ` (${s.reason_codes.join(", ")})` : ""}` : "none";
  return (
    <section className="card">
      <h3>Guardrails</h3>
      <div className="guards">
        <div><span>Injection</span>{injection}</div>
        <div><span>Hidden text removed</span>{label.facts.hidden_chars_removed ?? 0} characters</div>
        <div><span>Quotes</span>{verified} verified, {dropped} dropped</div>
        <div><span>Screen</span>{screen}</div>
        <div><span>Empty fields</span>{(label.facts.empty_fields ?? []).join(", ") || "none"}</div>
        <div><span>Cost and time</span>${label.cost_usd.toFixed(4)} · {(label.latency_ms / 1000).toFixed(1)} s</div>
      </div>
    </section>
  );
}

// The run's steps, read from its LangGraph checkpoints. Refreshes every half second while the job
// is queued or running, so a new posting fills in step by step.
function Timeline({ postingId }: { postingId: number }) {
  const [steps, setSteps] = useState<Steps | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () =>
      api.steps(postingId).then(
        (s) => {
          if (stop) return;
          setSteps(s);
          if (s.job && ["queued", "running"].includes(s.job.status)) timer = setTimeout(tick, 500);
        },
        (e) => !stop && setError(e),
      );
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [postingId]);
  const times = steps ? durations(steps.steps) : [];
  return (
    <section className="card">
      <h3>Steps{steps?.job && ["queued", "running"].includes(steps.job.status) ? ` · ${steps.job.status}` : ""}</h3>
      <ErrorNote error={error} />
      {steps?.job?.checkpoints_pruned && <p className="muted small">Steps are kept for 7 days; this run's were deleted.</p>}
      <ol className="steps" data-testid="steps">
        {steps?.steps.map((step, i) => (
          <li key={i} className={step.status}>
            <span className="n">{step.node}</span>{" "}
            <span className="d">
              · {step.status === "done" ? summary(step) : step.status}
              {times[i] != null && step.status === "done" ? ` · ${times[i]! < 1000 ? `${times[i]} ms` : `${(times[i]! / 1000).toFixed(1)} s`}` : ""}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function History({ label }: { label: Detail }) {
  const { sections } = useShared();
  return (
    <section className="card">
      <h3>Across versions</h3>
      <div className="hist">
        {label.history.map((h) => (
          <div key={h.id}>
            <Link className="mono" to={`/labels/${h.id}`}>{h.policy_version}</Link>
            <span>
              <LabelBadge label={h.label} /> {h.sections.map((s) => <SectionTag key={s} code={s} title={sections[s]} />)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
