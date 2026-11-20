import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, explain, type Detail, type Steps } from "../api";
import { ErrorNote, LabelBadge, SectionTag, color, useLoad } from "../components/ui";
import { useShared } from "../context";
import { segments, spansFor } from "../lib/highlight";
import { neighbours, readListContext } from "../lib/listContext";
import { durations, summary } from "../lib/steps";
import { field, location, modelName, reasonSentence, stepName } from "../lib/words";

const FIELDS: [string, string][] = [
  ["company_profile", "Company profile"],
  ["description", "Description"],
  ["requirements", "Requirements"],
  ["benefits", "Benefits"],
  ["salary_range", "Salary"],
];

// Ids for a highlight in the posting and for a section's row in "What the Labeling Agent found",
// so each can take you to the other.
const quoteId = (fieldName: string, start: number) => `q-${fieldName}-${start}`;
const sectionId = (code: string) => `found-${code.replace("§", "s")}`;

function flashTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.closest("details") && !(el.closest("details") as HTMLDetailsElement).open) (el.closest("details") as HTMLDetailsElement).open = true;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash");
  void el.offsetWidth; // restart the animation
  el.classList.add("flash");
}
const showQuote = (fieldName: string, start: number) => flashTo(quoteId(fieldName, start));
const showSection = (code: string) => flashTo(sectionId(code));

export default function Decision() {
  const { id = "" } = useParams();
  const { data, error, reload } = useLoad(() => api.label(id), [id]);
  if (error) return <div className="page"><ErrorNote error={error} /></div>;
  if (!data) return <div className="page muted">Loading…</div>;
  return (
    <div className="page">
      <ListNav label={data} />
      <div className="decision">
        <main>
          <Posting label={data} />
          <Found label={data} />
          <Timeline postingId={data.posting_id} />
          <History label={data} />
          <ApiAnswer label={data} />
        </main>
        <aside className="rail">
          <Verdict label={data} onDecided={reload} />
          <Checks label={data} />
        </aside>
      </div>
    </div>
  );
}

// Back to the page of the list you came from (filters and page kept), and through it.
function ListNav({ label }: { label: Detail }) {
  const ctx = readListContext();
  const { prev, next } = neighbours(ctx, label.id);
  return (
    <div className="crumb">
      <Link to={ctx?.url ?? "/"}>← Back to the list</Link>
      <span className="mono">job {label.job_id}</span>
      <span className="spacer" />
      {prev !== undefined && <Link className="btn small" to={`/labels/${prev}`}>← Previous posting</Link>}
      {next !== undefined && <Link className="btn small" to={`/labels/${next}`}>Next posting →</Link>}
    </div>
  );
}

// The posting as the models saw it (cleaned), as plain text. Verified quotes are highlighted from
// their stored positions, in their section's colour. React renders text, never HTML.
function Posting({ label }: { label: Detail }) {
  const c = label.cleaned;
  const meta = [location(c.location), c.employment_type, c.industry].filter(Boolean).join(" · ");
  return (
    <article className="doc">
      <h1>{c.title}</h1>
      <div className="meta">
        {meta && <>{meta} · </>}client {label.client_id} · {c.has_company_logo === "1" ? "logo shown" : "no logo"}
      </div>
      {FIELDS.map(([name, heading]) => (
        <section className="field" key={name}>
          <div className="label-text">{heading}</div>
          {c[name] ? (
            <p>
              {segments(c[name], spansFor(name, label.findings)).map((seg, i) =>
                seg.section ? (
                  <mark
                    key={i}
                    id={seg.start !== undefined ? quoteId(name, seg.start) : undefined}
                    data-section={seg.section}
                    style={{ "--c": color(seg.section) } as React.CSSProperties}
                    role="button"
                    tabIndex={0}
                    title={`Show what the agent found for ${seg.section}`}
                    onClick={() => showSection(seg.section!)}
                    onKeyDown={(e) => { if (e.key === "Enter") showSection(seg.section!); }}
                  >
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
  const why = shortWhy(label);
  return (
    <section className="card">
      <h2 className="card-title">Label</h2>
      <div className="verdict">
        <span className={`badge big ${label.label}`}>{label.label.replace("_", " ")}</span>
        {label.policy_sections.map((s) => <SectionTag key={s} code={s} title={sections[s]} />)}
      </div>
      <p className="rationale">{label.rationale}</p>
      <p className="hint" data-testid="why">
        {why}
        {label.confidence > 0 && (
          <> · <span className="has-tip" title={confidenceTip(label)}>Confidence {label.confidence.toFixed(2)}</span></>
        )}
      </p>
      {decision && (
        <div className="final" data-testid="analyst-decision">
          <b>Analyst decision: {decision.label.replace("_", " ").toLowerCase()}</b> (final) · {decision.analyst}
          {decision.note && <div>{decision.note}</div>}
        </div>
      )}
      {user.role !== "viewer" ? (
        <DecideForm labelId={label.id} onDecided={onDecided} />
      ) : (
        <p className="hint">Editors and publishers can record a decision.</p>
      )}
    </section>
  );
}

// Why the label is what it is, in one short line, from the findings.
function shortWhy(label: Detail): string {
  const codes = label.reason_codes;
  if (codes.includes("injection")) return "It tries to instruct an AI, so no model labeled it";
  if (codes.includes("dlq")) return "Labeling failed 3 times, so a person should look";
  const failure = codes.find((c) => ["llm_refusal", "llm_output_invalid", "clean_error"].includes(c));
  if (failure) return reasonSentence([failure]).replace(/\.$/, "");
  if (codes.includes("cleared_by_screen")) return "Jev scored every section low";
  const matched = label.findings.filter((f) => f.status === "matched").map((f) => f.section);
  const unsure = label.findings.filter((f) => f.status === "unsure").map((f) => f.section);
  if (label.label === "VIOLATING") return `Violates ${matched.join(", ")}`;
  const parts = [matched.length ? `${matched.join(", ")} matched` : "", unsure.length ? `${unsure.join(", ")} unsure` : ""].filter(Boolean);
  return parts.length ? parts.join(", ") : "No section matched";
}

// Where the confidence number comes from, shown on hover.
function confidenceTip(label: Detail): string {
  if (label.reason_codes.includes("cleared_by_screen")) return "One minus Jev's highest section score.";
  return "How sure Claude said it was about the section the label rests on: its own estimate, from 0 to 1.";
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
      <span className="label-text">Your decision: final outcome</span>
      <select aria-label="Your decision" value={choice} onChange={(e) => setChoice(e.target.value)}>
        <option value="VIOLATING">Violating</option>
        <option value="NEEDS_REVIEW">Needs review</option>
        <option value="ALLOWED">Allowed</option>
      </select>
      <input aria-label="Note" placeholder="Note for the record" value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="submit" className="primary">Record decision</button>
      {message && <p className="hint">{message}</p>}
    </form>
  );
}

// What the agent found, section by section: the sections the label rests on first, each with its
// reasoning, its quotes (click one to see it in the posting), the empty fields it rests on and any
// quotes it gave that weren't in the posting. Sections that didn't match fold into one line.
function Found({ label }: { label: Detail }) {
  const { sections } = useShared();
  const scores: Record<string, number> = label.screen?.scores ?? {};
  const order = { matched: 0, unsure: 1, not_matched: 2 } as Record<string, number>;
  const findings = [...label.findings].sort((a, b) => order[a.status] - order[b.status]);
  const relevant = findings.filter((f) => f.status !== "not_matched");
  const others = findings.filter((f) => f.status === "not_matched");

  const row = (f: Detail["findings"][number]) => (
    <div className={`finding ${f.status}`} key={f.section} id={sectionId(f.section)}>
      <span className="code" style={{ color: color(f.section) }}>{f.section}</span>
      <span className="name">{sections[f.section] ?? ""}</span>
      <span className="st">{f.status === "not_matched" ? "not matched" : f.status}</span>
      <span className="r">{f.reasoning}</span>
      {f.quotes.length > 0 && (
        <ul className="evidence-list">
          {f.quotes.map((q) => (
            <li key={`${q.field}-${q.start}`}>
              <button className="quote" style={{ borderLeftColor: color(f.section) }} onClick={() => showQuote(q.field, q.start)} title="Show it in the posting">
                “{q.text}”
                <span className="where">{field(q.field)} · show in the posting</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {f.missing_fields.length > 0 && <span className="r">Rests on empty fields: {f.missing_fields.map(field).join(", ")}.</span>}
      {f.dropped_quotes.length > 0 && (
        <span className="r hint">
          Discarded, not in the posting word for word: {f.dropped_quotes.map((d) => `“${d}”`).join(", ")}.
        </span>
      )}
      <span className="nums">
        Claude {f.confidence.toFixed(2)}
        {scores[f.section] !== undefined && <> · Jev {Number(scores[f.section]).toFixed(2)}</>}
      </span>
    </div>
  );

  return (
    <section className="card found" data-testid="found">
      <h2 className="card-title">What the Labeling Agent found</h2>
      {label.findings.length === 0 && <p className="muted small">No model read this posting. See the reasons on the right.</p>}
      {label.findings.length > 0 && relevant.length === 0 && <p className="muted small">No section of the policy matched.</p>}
      {relevant.map(row)}
      {others.length > 0 && (
        <details className="others">
          <summary>
            {others.length} {others.length === 1 ? "section" : "sections"} not matched: {others.map((f) => f.section).join(", ")}
          </summary>
          {others.map(row)}
        </details>
      )}
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
  if (verified) items.push({ text: `${verified === 1 ? "The quote" : `All ${verified} quotes`} in the evidence ${verified === 1 ? "was" : "were"} found word for word in the posting.` });
  if (dropped.length) items.push({ warn: true, text: `${dropped.length} more ${dropped.length === 1 ? "quote was" : "quotes were"} discarded because ${dropped.length === 1 ? "it isn't" : "they aren't"} in the posting.` });
  if (empty.length) items.push({ text: `Left empty by the employer: ${empty.map(field).join(", ")}.` });
  if (label.cost_usd > 0) items.push({ text: `Labeling cost $${label.cost_usd.toFixed(4)} and took ${(label.latency_ms / 1000).toFixed(1)} s.` });

  return (
    <section className="card">
      <h2 className="card-title">Checks on this posting</h2>
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
      <h2 className="card-title">How it was labeled{steps?.job && ["queued", "running"].includes(steps.job.status) ? ` · ${steps.job.status}` : ""}</h2>
      <ErrorNote error={error} />
      {steps?.job?.checkpoints_pruned && <p className="muted small">Steps are kept for 7 days; this run's were deleted.</p>}
      <ol className="steps" data-testid="steps">
        {steps?.steps.map((step, i) => (
          <li key={i} className={step.status}>
            <span className="n">{stepName(step.node)}</span>{" "}
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
      <h2 className="card-title">This posting under each policy version</h2>
      <div className="hist">
        {label.history.map((h) => (
          <div key={h.id}>
            <Link className="mono" to={`/labels/${h.id}`}>{h.policy_version}{h.id === label.id ? " (this page)" : ""}</Link>
            <span>
              <LabelBadge label={h.label} /> {h.sections.map((s) => <SectionTag key={s} code={s} title={sections[s]} />)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

// Exactly what the marketplace gets for this posting from GET /v1/postings/{job_id}/label.
function ApiAnswer({ label }: { label: Detail }) {
  return (
    <section className="card">
      <details className="json">
        <summary>The API's answer (JSON)</summary>
        <p className="hint">What the marketplace gets from <code>GET /v1/postings/{label.job_id}/label</code>.</p>
        <pre data-testid="api-answer">{JSON.stringify(label.api_answer, null, 2)}</pre>
      </details>
      <p className="footer-line">
        Labeled {new Date(label.labeled_at).toLocaleString()} by {modelName(label.model_version)}, under policy {label.policy_version}.
      </p>
    </section>
  );
}
