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
        <Checks label={data} />
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
        <span className="muted">under policy {label.policy_version}</span>
      </div>
      <p className="hint">{confidenceText(label)}</p>
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

// Where the confidence number comes from, in words.
function confidenceText(label: Detail): string {
  const c = label.confidence.toFixed(2);
  if (label.reason_codes.includes("cleared_by_screen")) return `Confidence ${c}: one minus Jev's highest section score.`;
  if (label.confidence === 0) return "Confidence 0: no model judged this posting, so a person should.";
  return `Confidence ${c}: how sure the model said it was (0 to 1), for the section the label rests on. The model's own estimate, not a measured probability.`;
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
      <b className="small full">Your decision: final, and what the marketplace sees</b>
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

// What the system checked on this posting, as plain sentences. A "!" marks something to notice.
function Checks({ label }: { label: Detail }) {
  const s = label.screen ?? {};
  const dropped = label.findings.flatMap((f) => f.dropped_quotes);
  const verified = label.findings.reduce((n, f) => n + f.quotes.length, 0);
  const hidden = label.facts.hidden_chars_removed ?? 0;
  const empty: string[] = label.facts.empty_fields ?? [];
  const items: { text: string; warn?: boolean }[] = [];

  if (s.injection_flag) {
    items.push({
      warn: true,
      text: s.regex_hits?.length
        ? `It tries to give instructions to an AI ("${s.regex_hits[0]}"), so no AI model labeled it.`
        : `Jev rated it likely to give instructions to an AI (${s.injection.toFixed(2)}), so no AI model labeled it.`,
    });
  } else {
    items.push({ text: "No attempt to give instructions to an AI was found." });
  }
  items.push(
    hidden
      ? { warn: true, text: `${hidden} characters of hidden text were removed before any model read it.` }
      : { text: "No hidden text." },
  );
  if (s.cleared) items.push({ text: "Jev scored every section low, so Claude wasn't needed." });
  else if (s.used === "jev" || s.used === "haiku") items.push({ text: `${s.used === "jev" ? "Jev" : "Haiku"} couldn't rule every section out, so Claude read it.` });
  if ((s.reason_codes ?? []).includes("screen_unavailable")) items.push({ warn: true, text: "The screen was unavailable, so Claude read it directly." });
  if (verified) items.push({ text: `${verified === 1 ? "The quote" : `All ${verified} quotes`} shown above ${verified === 1 ? "was" : "were"} found word for word in the posting.` });
  if (dropped.length) items.push({ warn: true, text: `${dropped.length} more ${dropped.length === 1 ? "quote was" : "quotes were"} discarded because ${dropped.length === 1 ? "it isn't" : "they aren't"} in the posting.` });
  if (empty.length) items.push({ text: `Left empty by the employer: ${empty.map((f) => f.replace("_", " ")).join(", ")}.` });
  if (label.cost_usd > 0) items.push({ text: `Labeling cost $${label.cost_usd.toFixed(4)} and took ${(label.latency_ms / 1000).toFixed(1)} s.` });

  return (
    <section className="card">
      <h3>Checks on this posting</h3>
      <ul className="checks">
        {items.map((item, i) => <li key={i} className={item.warn ? "warn" : ""}>{item.text}</li>)}
      </ul>
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
