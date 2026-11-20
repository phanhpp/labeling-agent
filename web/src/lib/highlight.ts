// Turn a field's text and the verified quote positions into plain segments for React to render.
// Positions come from the API (start/end into the cleaned text), so a highlight never has to search
// the text. The result is plain strings: React renders them as text, never as HTML.

export type Span = { field: string; start: number; end: number; section: string };
export type Segment = { text: string; section?: string };

export function segments(text: string, spans: Span[]): Segment[] {
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const out: Segment[] = [];
  let at = 0;
  for (const span of sorted) {
    const start = Math.max(span.start, at); // an overlapping quote continues where the last one ended
    const end = Math.min(span.end, text.length);
    if (end <= start) continue;
    if (start > at) out.push({ text: text.slice(at, start) });
    out.push({ text: text.slice(start, end), section: span.section });
    at = end;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

// The verified quotes of one field, with the section each one supports, from a label's findings.
export function spansFor(
  field: string,
  findings: { section: string; quotes: { field: string; start: number; end: number }[] }[],
): Span[] {
  return findings.flatMap((f) =>
    f.quotes.filter((q) => q.field === field).map((q) => ({ ...q, section: f.section })),
  );
}
