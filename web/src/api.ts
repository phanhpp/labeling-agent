// Every call to the API. Each request carries the acting user's token; the API decides what that
// role may do. Errors come back as ApiError with the API's code (e.g. "forbidden", "four_eyes").

import { pageWindow, type Filters } from "./lib/filters";
import type { RelabelCounts } from "./lib/words";

export class ApiError extends Error {
  constructor(public status: number, public code: string, public detail?: unknown) {
    super(code);
  }
}

let token = "";
export const setToken = (t: string) => (token = t);

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError(0, "api_unreachable");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok && response.status !== 202) {
    const error = body?.error;
    if (typeof error === "object" && error) throw new ApiError(response.status, error.code, error.detail);
    throw new ApiError(response.status, typeof error === "string" ? error : `http_${response.status}`);
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({ method, body: data === undefined ? undefined : JSON.stringify(data) });

export type Quote = { text: string; field: string; start: number; end: number };
export type Finding = {
  section: string; status: string; reasoning: string; quotes: Quote[]; confidence: number;
  missing_fields: string[]; dropped_quotes: string[];
};
export type Match = { section: string; status: string; quotes: Quote[]; missing_fields: string[]; reasoning: string };
export type LabelRow = {
  id: number; posting_id: number; job_id: string; title: string; label: string; sections: string[];
  confidence: number; rationale: string; reason_codes: string[]; policy_version: string; decision: string | null;
  policy_match: Match[];
  evidence_preview: { section: string; text?: string; missing?: string[] } | null;
};
export type Browse = { version: string; items: LabelRow[]; total: number; counts: { label: Record<string, number>; section: Record<string, number> } };
export type Detail = {
  id: number; posting_id: number; job_id: string; client_id: string; label: string; policy_sections: string[];
  rationale: string; confidence: number; policy_version: string; reason_codes: string[]; findings: Finding[];
  screen: Record<string, any> | null; model_version: string; cleaned: Record<string, string>; facts: Record<string, any>;
  cost_usd: number; latency_ms: number; labeled_at: string;
  history: { id: number; policy_version: string; label: string; sections: string[]; created_at: string }[];
  decisions: { label: string; note: string; analyst: string; policy_version: string; created_at: string }[];
  job: { status: string } | null;
  api_answer: Record<string, unknown> | null;
};
export type Steps = { job: { status: string; checkpoints_pruned: boolean } | null; steps: import("./lib/steps").Step[] };
export type Version = {
  name: string; status: "draft" | "live" | "retired"; parent: string | null; author: string; edited_by: string[];
  published_by: string | null; published_at: string | null; tested: boolean; created_at: string;
  submitted_by: string | null; submitted_at: string | null;
};
export type CompareRow = {
  posting_id: number; job_id: string; title: string; changed: boolean; from_the_change: boolean;
  old: { label_id: number; label: string; sections: string[] }; new: { label_id: number; label: string; sections: string[] };
};
export type Comparison = { old: string; new: string; postings: number; changed: number; from_the_change: number; rows: CompareRow[] };
export type Policy = Version & { body: any; relabel_scope?: number; test_labels?: number; diff?: { against: string; changes: { where: string; change: string; models_see_it: boolean }[] } };
export type Flip = { job_id: string; label_id: number; before: { label: string; sections: string[] }; after: { label: string; sections: string[] }; from_the_change: boolean };
export type Report = {
  version: string; compared_with: string; mode: string; jobs: Record<string, number>; labeled: number;
  changed: Record<string, number>; flips: Flip[]; flips_from_the_change: number; model_calls: number; cost_usd: number;
  invariants: { name: string; passed: boolean }[]; passed: boolean; tested_current_content: boolean;
};
export type { RelabelCounts };
export type Relabel = {
  version: string; status: string; labels: number; labels_without_a_model_call: number; cost_usd: number;
  jobs: Record<string, number>; relabel: RelabelCounts | null; new_postings: number;
};
export type Health = { live_labeling: boolean; missing_keys: string[]; agent_config: string; llm_backend: string };

export const api = {
  health: () => request<Health>("/health"),
  labels: (filters: Filters) => {
    const { limit, offset } = pageWindow(filters);
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    for (const key of ["label", "section", "job_id", "version"] as const) if (filters[key]) params.set(key, filters[key]!);
    return request<Browse>(`/ui/labels?${params}`);
  },
  label: (id: string) => request<Detail>(`/ui/labels/${id}`),
  steps: (postingId: number) => request<Steps>(`/ui/postings/${postingId}/steps`),
  decide: (id: number, label: string, note: string) => request(`/ui/labels/${id}/decision`, json("POST", { label, note })),
  versions: () => request<Version[]>("/policies"),
  version: (name: string, diff?: string | null) => request<Policy>(`/policies/${name}${diff ? `?diff=${diff}` : ""}`),
  createDraft: (name: string) => request<Version>("/policies/drafts", json("POST", { name })),
  saveDraft: (name: string, body: any) => request<Version>(`/policies/drafts/${name}`, json("PUT", { body })),
  startTest: (name: string, limit = 100) => request(`/policies/drafts/${name}/test?limit=${limit}`, json("POST")),
  discardDraft: (name: string) => request<{ discarded: string; labels_deleted: number }>(`/policies/drafts/${name}`, json("DELETE")),
  stopTest: (name: string) => request<{ dropped: number }>(`/policies/drafts/${name}/test/stop`, json("POST")),
  submit: (name: string) => request<Version>(`/policies/drafts/${name}/submit`, json("POST")),
  compare: (from: string, to: string) => request<Comparison>(`/ui/compare?from=${from}&to=${to}`),
  report: (name: string) => request<Report>(`/policies/drafts/${name}/test`),
  publish: (name: string) => request<{ mode: string; queued: number; redecided: number }>(`/policies/drafts/${name}/publish`, json("POST")),
  rollback: (name: string) => request(`/policies/live`, json("PUT", { name })),
  relabel: (name: string) => request<Relabel>(`/policies/${name}/relabel`),
};

// What an error means, in plain words for the page.
const MESSAGES: Record<string, string> = {
  api_unreachable: "Can't reach the API. Is it running (docker compose up)?",
  unauthenticated: "The API doesn't recognise this user's token.",
  forbidden: "This user's role can't do that.",
  four_eyes: "You edited this draft, so a different publisher has to publish it.",
  test_outdated: "The draft changed after its last Test, or was never tested. Run Test first.",
  test_not_passed: "The Test hasn't finished, or one of its checks failed.",
  parent_not_live: "The version this draft started from is no longer live. Create the draft again.",
  not_a_draft: "Published versions can't be edited or discarded.",
  test_running: "The Test is still running. Stop it, wait a few seconds, then try again.",
  draft_in_use: "Labels under another version were copied from this draft's Test, so it can't be discarded.",
  name_taken: "A version with that name already exists.",
  not_retired: "Only a version that was live before can be made live again.",
  invalid_policy: "The policy isn't valid.",
  not_found: "Not found.",
  rate_limited: "Too many requests. Try again in a minute.",
};

export function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const base = MESSAGES[error.code] ?? `Error: ${error.code}`;
    return error.code === "invalid_policy" && typeof error.detail === "string" ? `${base} ${error.detail}` : base;
  }
  return "Something went wrong.";
}
