import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type Relabel } from "../api";
import { relabelSentence } from "../lib/words";

// A version's re-label, read again every 1.5 s while postings are still waiting, so a publish can
// be watched as it happens. Read once otherwise.
export function useRelabel(name: string | null): Relabel | null {
  const [data, setData] = useState<Relabel | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!name) return setData(null);
    let current = true;
    api.relabel(name).then((r) => current && setData(r), () => {});
    return () => { current = false; };
  }, [name, tick]);
  const waiting = data?.version === name ? (data?.relabel?.waiting ?? 0) : 0;
  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(() => setTick((n) => n + 1), 1500);
    return () => clearTimeout(timer);
  }, [data, waiting]);
  return data?.version === name ? data : null;
}

// The re-label as a bar and a sentence. Nothing for a version that re-labeled nothing (v1, loaded
// at startup, or a version made live again by rollback).
// from: the version it replaced, to point at Compare from → this version.
export function RelabelProgress({ relabel, compact = false, from = null }: { relabel: Relabel | null; compact?: boolean; from?: string | null }) {
  const r = relabel?.relabel;
  if (!relabel || !r || r.total === 0) return null;
  const done = r.kept_from_test + r.relabeled;
  return (
    <div className={`relabel ${r.waiting ? "running" : "finished"}`} data-testid={compact ? "relabel-panel" : "relabel"}>
      <div className="bar" role="progressbar" aria-label={`Re-label under ${relabel.version}`} aria-valuemin={0} aria-valuemax={r.total} aria-valuenow={done}>
        <span className="kept" style={{ width: `${(100 * r.kept_from_test) / r.total}%` }} />
        <span className="done" style={{ width: `${(100 * r.relabeled) / r.total}%` }} />
      </div>
      <p className={compact ? "small" : ""}>
        {compact
          ? r.waiting
            ? `Re-labeling under ${relabel.version}: ${done} of ${r.total}, ${r.kept_from_test} kept from the Test.`
            : `${relabel.version}: all ${r.total} recent postings re-labeled, ${r.kept_from_test} kept from the Test.`
          : relabelSentence(relabel.version, r)}
      </p>
      {!compact && from && (r.waiting ? (
        <p className="muted small">When it's done, Compare {from} → {relabel.version} lists every label that changed.</p>
      ) : (
        <p className="relabel-next">
          Done. <Link className="btn small" to={`/compare?from=${from}&to=${relabel.version}`}>See what changed: Compare {from} → {relabel.version}</Link>
        </p>
      ))}
      {!compact && relabel.new_postings > 0 && (
        <p className="muted small">{relabel.new_postings} new postings labeled under {relabel.version} since it went live.</p>
      )}
    </div>
  );
}
