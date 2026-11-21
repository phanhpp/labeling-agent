// Internal names the API uses, said in plain words for the page.

const REASONS: Record<string, string> = {
  review_section_matched: "a section that sends postings to review matched",
  section_unsure: "Claude was unsure about a section",
  quote_unverified: "a quote Claude gave couldn't be found in the posting",
  injection: "the posting seems to give instructions to an AI",
  cleared_by_screen: "Jev scored every section low, so Claude wasn't needed",
  screen_fallback: "Jev was unavailable, so Haiku screened it",
  screen_unavailable: "no screen was available, so Claude read it directly",
  cached: "the same posting was labeled before, so that label was reused",
  dlq: "labeling failed 3 times, so a person should look",
  llm_refusal: "Claude declined to answer",
  llm_output_invalid: "Claude's answer couldn't be read",
  clean_error: "the posting couldn't be cleaned",
};

export const reason = (code: string) => REASONS[code] ?? code.replaceAll("_", " ");

// "Held for review because a section ... and Claude was unsure ...", or "" when there is nothing to say.
export function reasonSentence(codes: string[]): string {
  const parts = codes.map(reason);
  if (parts.length === 0) return "";
  const joined = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
  return joined.charAt(0).toUpperCase() + joined.slice(1) + ".";
}

const FIELDS: Record<string, string> = {
  company_profile: "company profile",
  company_logo: "logo",
  salary_range: "salary",
  requirements: "requirements",
  benefits: "benefits",
  description: "description",
  title: "title",
};

export const field = (name: string) => FIELDS[name] ?? name.replaceAll("_", " ");

const STEPS: Record<string, string> = {
  clean: "Cleaned",
  cache: "Earlier label",
  screen: "Quick screen (Jev)",
  escalate: "Claude read it",
  check: "Quotes checked",
  decide: "Label set",
};

export const stepName = (node: string) => STEPS[node] ?? node;

// "GB, , London" -> "GB, London"; empty parts of the dataset's location are dropped.
export const location = (raw: string | undefined) =>
  (raw ?? "").split(",").map((p) => p.trim()).filter(Boolean).join(", ");

// The model id as people say it.
export function modelName(modelVersion: string): string {
  if (modelVersion.startsWith("fake;")) return "the sample stand-in (no AI model)";
  const screen = /screen=(\w+)/.exec(modelVersion)?.[1];
  const claude = modelVersion.includes("claude-sonnet") ? "Claude Sonnet 5.5" : modelVersion.includes("claude-haiku") ? "Claude Haiku 5.5" : "the model";
  return screen && screen !== "none" ? `${screen === "jev" ? "Jev" : "Haiku"} + ${claude}` : claude;
}

// Where a version's re-label stands, in one sentence: what Publish kept from the Test, what it
// labeled again (in code at $0, or with the models), and what is still waiting.
export type RelabelCounts = { kept_from_test: number; relabeled: number; in_code: number; waiting: number; total: number; cost_usd: number };

export const dollars = (usd: number) => (usd > 0 && usd < 0.01 ? "under $0.01" : `$${usd.toFixed(2)}`);

export function relabelSentence(version: string, r: RelabelCounts): string {
  const done = r.kept_from_test + r.relabeled;
  const head = r.waiting
    ? `Labeling recent postings again under ${version}: ${done} of ${r.total} done.`
    : `All ${r.total} recent postings are labeled under ${version}.`;
  const parts = [`${r.kept_from_test} kept from the Test`];
  parts.push(r.in_code ? `${r.relabeled} labeled again (${r.in_code} decided in code at $0)` : `${r.relabeled} labeled again`);
  if (r.waiting) parts.push(`${r.waiting} waiting`);
  return `${head} ${parts.join(", ")}. Cost ${r.waiting ? "so far " : ""}${dollars(r.cost_usd)}.`;
}

// "1 false alarm", "2 false alarms".
export const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

// A stored user id ("eddie") as the name people see ("Eddie").
export const person = (id: string | null | undefined) => (id ? id.charAt(0).toUpperCase() + id.slice(1) : "");
