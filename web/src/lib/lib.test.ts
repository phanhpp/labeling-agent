import { describe, expect, it } from "vitest";
import { readFilters, toParams, toggle } from "./filters";
import { segments, spansFor } from "./highlight";
import { durations, summary } from "./steps";

describe("highlight segments", () => {
  const text = "Pay the registration fee of $120 before your first shift.";

  it("cuts the text at each quote and keeps the rest as plain text", () => {
    const out = segments(text, [{ field: "d", start: 8, end: 32, section: "§1" }]);
    expect(out).toEqual([
      { text: "Pay the " },
      { text: "registration fee of $120", section: "§1" },
      { text: " before your first shift." },
    ]);
    expect(out.map((s) => s.text).join("")).toBe(text);
  });

  it("handles quotes out of order, overlapping, at the edges or past the end", () => {
    const out = segments(text, [
      { field: "d", start: 33, end: 999, section: "§2" },
      { field: "d", start: 0, end: 12, section: "§1" },
      { field: "d", start: 4, end: 20, section: "§5" },
    ]);
    expect(out.map((s) => s.text).join("")).toBe(text);
    expect(out[0]).toEqual({ text: "Pay the regi", section: "§1" });
    expect(out[1]).toEqual({ text: "stration", section: "§5" });
    expect(out.at(-1)).toEqual({ text: "before your first shift.", section: "§2" });
  });

  it("leaves markup as text: segments are strings, never HTML", () => {
    const html = "<script>window.pwned=1</script> ok";
    expect(segments(html, [])).toEqual([{ text: html }]);
  });

  it("takes each field's quotes from the findings, with their section", () => {
    const findings = [
      { section: "§1", quotes: [{ field: "description", start: 1, end: 5 }] },
      { section: "§5", quotes: [{ field: "company_profile", start: 0, end: 3 }] },
    ];
    expect(spansFor("description", findings)).toEqual([{ field: "description", start: 1, end: 5, section: "§1" }]);
  });
});

describe("URL filters", () => {
  it("reads only known, valid values", () => {
    const params = new URLSearchParams("label=VIOLATING&section=§1&job_id=%2042%20&other=x&version=v2");
    expect(readFilters(params)).toEqual({ label: "VIOLATING", section: "§1", job_id: "42", version: "v2" });
    expect(readFilters(new URLSearchParams("label=MAYBE&section=drop table"))).toEqual({});
  });

  it("round-trips through the URL and drops empty values", () => {
    const filters = { label: "ALLOWED" as const, section: "§5" };
    expect(readFilters(toParams(filters))).toEqual(filters);
    expect(toParams({ job_id: "" }).toString()).toBe("");
  });

  it("toggles a chip on, off, or to another value", () => {
    expect(toggle({}, "label", "VIOLATING")).toEqual({ label: "VIOLATING" });
    expect(toggle({ label: "VIOLATING" }, "label", "VIOLATING")).toEqual({});
    expect(toggle({ label: "VIOLATING", section: "§1" }, "label", "ALLOWED")).toEqual({ label: "ALLOWED", section: "§1" });
  });
});

describe("step lines", () => {
  const at = (s: number) => new Date(Date.UTC(2026, 10, 20, 0, 0, s)).toISOString();

  it("summarises what each node wrote", () => {
    expect(summary({ node: "screen", status: "done", started_at: at(0), output: { screen: { injection_flag: true } } }))
      .toBe("suspected injection: held for review");
    expect(summary({ node: "screen", status: "done", started_at: at(0), output: { screen: { used: "jev", cleared: true, scores: { "§1": 0.05, "§5": 0.12 } } } }))
      .toBe("jev: cleared, highest §5 0.12");
    expect(summary({ node: "check", status: "done", started_at: at(0), output: { checked: { findings: [
      { section: "§1", status: "matched", dropped_quotes: ["x"] }, { section: "§2", status: "not_matched" }] } } }))
      .toBe("matched §1, 1 quotes dropped");
    expect(summary({ node: "decide", status: "done", started_at: at(0), output: { decision: { label: "NEEDS_REVIEW" } } }))
      .toBe("NEEDS REVIEW");
  });

  it("times each step until the next one started", () => {
    const steps = [0, 2, 7].map((s, i) => ({ node: `n${i}`, status: "done", started_at: at(s), output: {} }));
    expect(durations(steps)).toEqual([2000, 5000, null]);
  });
});
