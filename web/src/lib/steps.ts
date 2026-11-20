// One line per step of the agent's run, from what each node wrote to its checkpoint.

export type Step = { node: string; status: string; started_at: string; output: Record<string, any> };

export function summary(step: Step): string {
  const o = step.output;
  switch (step.node) {
    case "clean": {
      const facts = o.facts ?? {};
      const parts = [`${(facts.empty_fields ?? []).length} empty fields`];
      if (facts.hidden_chars_removed) parts.push(`${facts.hidden_chars_removed} hidden characters removed`);
      return parts.join(", ");
    }
    case "cache":
      return o.decision ? "the same posting was labeled before: label reused" : "not labeled before";
    case "screen": {
      const s = o.screen ?? {};
      if (s.injection_flag) return "suspected injection: held for review";
      if (s.used === "none") return (s.reason_codes ?? []).includes("screen_unavailable") ? "screen unavailable" : "no screen";
      const top = Object.entries(s.scores ?? {}).sort((a: any, b: any) => b[1] - a[1])[0];
      const who = s.used === "jev" ? "Jev" : "Haiku";
      const high = top ? ` (highest ${top[0]} at ${Number(top[1]).toFixed(2)})` : "";
      return s.cleared ? `${who}: every section low, Claude not needed${high}` : `${who}: not clear enough to skip Claude${high}`;
    }
    case "escalate": {
      const u = (o.usage ?? [])[0];
      if (o.failure) return `failed: ${o.failure}`;
      const name = String(u?.model ?? "").includes("sonnet") ? "Claude Sonnet 5.5" : String(u?.model ?? "").includes("haiku") ? "Claude Haiku 5.5" : u?.model;
      return u ? `${name} answered, $${Number(u.cost_usd ?? 0).toFixed(4)}` : "the model answered";
    }
    case "check": {
      const findings: any[] = o.checked?.findings ?? [];
      const matched = findings.filter((f) => f.status === "matched").map((f) => f.section);
      const dropped = findings.reduce((n, f) => n + (f.dropped_quotes?.length ?? 0), 0);
      return `${matched.length ? `matched ${matched.join(", ")}` : "nothing matched"}${dropped ? `, ${dropped} quotes dropped` : ""}`;
    }
    case "decide":
      return o.decision ? o.decision.label.replace("_", " ") : "";
    default:
      return "";
  }
}

// How long each step took: until the next one started (the last one has no end).
export function durations(steps: Step[]): (number | null)[] {
  return steps.map((step, i) =>
    i + 1 < steps.length ? Date.parse(steps[i + 1].started_at) - Date.parse(step.started_at) : null,
  );
}
