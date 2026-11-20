// Browse filters live in the URL (?label=VIOLATING&section=§1), so a filtered view can be shared
// and survives a reload.

export const LABELS = ["NEEDS_REVIEW", "VIOLATING", "ALLOWED"] as const;
export type Label = (typeof LABELS)[number];
export type Filters = { label?: Label; section?: string; job_id?: string; version?: string };

const KEYS = ["label", "section", "job_id", "version"] as const;

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
  return out;
}

export function toParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  return params;
}

// Clicking the chip that is on turns it off; any other chip replaces it.
export function toggle(filters: Filters, key: "label" | "section", value: string): Filters {
  const next = { ...filters };
  if (next[key] === value) delete next[key];
  else (next as Record<string, string>)[key] = value;
  return next;
}
