// Browse filters live in the URL (?label=VIOLATING&section=§1), so a filtered view can be shared
// and survives a reload.

export const LABELS = ["NEEDS_REVIEW", "VIOLATING", "ALLOWED"] as const;
export type Label = (typeof LABELS)[number];
// batch: only one live-demo run's postings. disagree: only where our label and the dataset's differ.
export type Filters = {
  label?: Label; section?: string; job_id?: string; version?: string; page?: number; per?: number;
  batch?: number; disagree?: boolean;
};

const KEYS = ["label", "section", "job_id", "version", "page", "per", "batch", "disagree"] as const;
export const PAGE_SIZES = [10, 25, 50, 100] as const;
export const DEFAULT_PER = 25;

export function readFilters(params: URLSearchParams): Filters {
  const out: Filters = {};
  const label = params.get("label");
  if (label && (LABELS as readonly string[]).includes(label)) out.label = label as Label;
  const section = params.get("section");
  if (section && /^§\d+$/.test(section)) out.section = section;
  const jobId = params.get("job_id")?.trim();
  if (jobId) out.job_id = jobId;
  const version = params.get("version");
  if (version) out.version = version;
  const page = Number(params.get("page"));
  if (Number.isInteger(page) && page > 1) out.page = page;
  const per = Number(params.get("per"));
  if ((PAGE_SIZES as readonly number[]).includes(per) && per !== DEFAULT_PER) out.per = per;
  const batch = Number(params.get("batch"));
  if (Number.isInteger(batch) && batch > 0) out.batch = batch;
  if (params.get("disagree") === "1") out.disagree = true;
  return out;
}

// The API's limit and offset for the page the filters ask for.
export function pageWindow(filters: Filters): { limit: number; offset: number } {
  const per = filters.per ?? DEFAULT_PER;
  return { limit: per, offset: ((filters.page ?? 1) - 1) * per };
}

export function toParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = filters[key];
    if (value === true) params.set(key, "1");
    else if (value) params.set(key, String(value));
  }
  return params;
}

// Clicking the chip that is on turns it off; any other chip replaces it.
// Changing a filter goes back to the first page.
export function toggle(filters: Filters, key: "label" | "section", value: string): Filters {
  const next = { ...filters };
  delete next.page;
  if (next[key] === value) delete next[key];
  else (next as Record<string, string>)[key] = value;
  return next;
}

// The policy's sections in order (§1, §2, ... §10), each with its count; a count for a section the
// policy doesn't have (an older version's) is kept too.
export function sectionCodes(titles: Record<string, string>, counts: Record<string, number>): [string, number][] {
  const codes = [...new Set([...Object.keys(titles), ...Object.keys(counts)])];
  const num = (code: string) => Number(code.replace(/\D/g, "")) || 0;
  return codes.sort((a, b) => num(a) - num(b)).map((code) => [code, counts[code] ?? 0]);
}

// Our label against the dataset's, for the demo's comparison. VIOLATING or NEEDS_REVIEW counts as
// flagging fraud: the same rule as the eval.
export type Verdict = "caught" | "missed fraud" | "false alarm" | "agrees";
export function datasetVerdict(label: string, dataset: "fraud" | "legitimate"): Verdict {
  const flagged = label === "VIOLATING" || label === "NEEDS_REVIEW";
  if (dataset === "fraud") return flagged ? "caught" : "missed fraud";
  return flagged ? "false alarm" : "agrees";
}
