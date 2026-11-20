import { useCallback, useEffect, useState } from "react";
import { explain } from "../api";

export const SECTION_COLOR: Record<string, string> = {
  "§1": "var(--s1)", "§2": "var(--s2)", "§3": "var(--s3)", "§4": "var(--s4)", "§5": "var(--s5)", "§6": "var(--s6)",
};
export const color = (section: string) => SECTION_COLOR[section] ?? "var(--muted)";

export function LabelBadge({ label }: { label: string }) {
  return <span className={`badge ${label}`}>{label.replace("_", " ")}</span>;
}

export function SectionTag({ code, title }: { code: string; title?: string }) {
  return (
    <span className="sec" style={{ color: color(code) }} title={title}>
      {code}
    </span>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="error" role="alert">{explain(error)}</p>;
}

// Load data, show loading and errors, and load again on demand or when a dependency changes.
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const reload = useCallback(() => {
    load().then(
      (value) => { setData(value); setError(null); },
      (e) => setError(e),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, reload };
}
