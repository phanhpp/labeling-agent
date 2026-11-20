import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { Match } from "../api";
import { field } from "../lib/words";
import { color } from "./ui";

// One chip per section a label rests on. Clicking it shows that section's evidence and Claude's
// reasoning in place; Escape or a click outside closes it.
export function PolicyMatch({ match, titles, labelId, reasons = [] }: { match: Match[]; titles: Record<string, string>; labelId: number; reasons?: string[] }) {
  if (match.length === 0 && reasons.includes("injection")) {
    return <span className="badge NEEDS_REVIEW" title="It tries to give instructions to an AI, so no AI model labeled it">Injection attempt</span>;
  }
  if (match.length === 0) return <span className="muted small">None</span>;
  return (
    <>
      {match.map((m) => (
        <MatchChip key={m.section} m={m} title={titles[m.section] ?? ""} labelId={labelId} />
      ))}
    </>
  );
}

function MatchChip({ m, title, labelId }: { m: Match; title: string; labelId: number }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const short = title.split("/")[0].trim();
  return (
    <span className="match" ref={box} onClick={(e) => e.stopPropagation()}>
      <button
        className={m.status === "unsure" ? "unsure" : ""}
        style={{ color: color(m.section) }}
        aria-expanded={open}
        aria-label={`${m.section} ${title}${m.status === "unsure" ? ", unsure" : ""}: show the evidence`}
        onClick={() => setOpen((o) => !o)}
      >
        <span><span className="match-name">{m.section} {short}</span>{m.status === "unsure" && <span className="match-unsure"> · unsure</span>}</span>
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label={`${m.section} evidence`} style={{ color: color(m.section) }}>
          <h4 style={{ color: color(m.section) }}>
            {m.section} {title}
          </h4>
          <p className="small muted">{m.status === "matched" ? "Matched" : "Claude was unsure"}</p>
          {m.quotes.map((q, i) => (
            <blockquote key={i}>
              “{q.text}” <span className="muted small">({field(q.field)})</span>
            </blockquote>
          ))}
          {m.missing_fields.length > 0 && (
            <p>Rests on empty fields: {m.missing_fields.map(field).join(", ")}.</p>
          )}
          {m.quotes.length === 0 && m.missing_fields.length === 0 && <p>No quote: see the reasoning.</p>}
          <p>{m.reasoning}</p>
          <Link className="small" to={`/labels/${labelId}`}>Open posting →</Link>
        </div>
      )}
    </span>
  );
}
