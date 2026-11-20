import { describe, expect, it } from "vitest";
import { datasetVerdict, pageWindow, readFilters, sectionCodes, toggle, toParams } from "./filters";
import { segments, spansFor } from "./highlight";
import { durations, summary } from "./steps";

describe("highlight segments", () => {
  const text = "Pay the registration fee of $120 before your first shift.";

  it("cuts the text at each quote and keeps the rest as plain text", () => {
    const out = segments(text, [{ field: "d", start: 8, end: 32, section: "§1" }]);
    expect(out).toEqual([
      { text: "Pay the " },
      { text: "registration fee of $120", section: "§1", start: 8 },
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
    expect(out[0]).toEqual({ text: "Pay the regi", section: "§1", start: 0 });
    expect(out[1]).toEqual({ text: "stration", section: "§5", start: 4 });
    expect(out.at(-1)).toEqual({ text: "before your first shift.", section: "§2", start: 33 });
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
      .toBe("Jev: every section low, Claude not needed (highest §5 at 0.12)");
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

describe("paging", () => {
  it("reads the page and the page size from the URL, ignoring bad values", () => {
    expect(readFilters(new URLSearchParams("page=3&per=50"))).toEqual({ page: 3, per: 50 });
    expect(readFilters(new URLSearchParams("page=0&per=7"))).toEqual({});
    expect(readFilters(new URLSearchParams("per=10"))).toEqual({ per: 10 });
    expect(readFilters(new URLSearchParams("page=1&per=25"))).toEqual({}); // the defaults stay out of the URL
  });

  it("turns a page into the API's limit and offset", () => {
    expect(pageWindow({})).toEqual({ limit: 25, offset: 0 });
    expect(pageWindow({ page: 3, per: 50 })).toEqual({ limit: 50, offset: 100 });
  });

  it("goes back to the first page when a filter changes", () => {
    expect(toggle({ page: 4 }, "label", "ALLOWED")).toEqual({ label: "ALLOWED" });
  });
});

describe("version tags", async () => {
  const { tagVersions } = await import("../context");
  const v = (name: string, status: string, published_at: string | null) => ({ name, status, published_at }) as any;

  it("tags the newest published as latest, the one before as previous, and the live one", () => {
    const tagged = tagVersions([
      v("v1", "retired", "2026-11-20T01:00:00Z"),
      v("v2", "live", "2026-11-20T02:00:00Z"),
      v("v3", "draft", null),
    ]);
    expect(tagged.map((t) => [t.name, t.tags])).toEqual([
      ["v1", ["previous"]],
      ["v2", ["latest", "live"]],
      ["v3", []],
    ]);
  });

  it("after a rollback, live and latest are different versions", () => {
    const tagged = tagVersions([v("v1", "live", "2026-11-20T01:00:00Z"), v("v2", "retired", "2026-11-20T02:00:00Z")]);
    expect(tagged.map((t) => t.tags)).toEqual([["previous", "live"], ["latest"]]);
  });
});

describe("section filter", () => {
  it("lists every section of the policy, in order, with 0 for those no posting matches", () => {
    const titles = { "§10": "Ten", "§2": "Two", "§1": "One" };
    expect(sectionCodes(titles, { "§2": 4 })).toEqual([["§1", 0], ["§2", 4], ["§10", 0]]);
  });
  it("keeps a count for a section the policy no longer has", () => {
    expect(sectionCodes({ "§1": "One" }, { "§6": 2 })).toEqual([["§1", 0], ["§6", 2]]);
  });
});

describe("live-demo filters and the dataset comparison", () => {
  it("keeps a run and the disagreement switch in the URL", () => {
    const f = readFilters(new URLSearchParams("batch=12&disagree=1&label=ALLOWED"));
    expect(f).toEqual({ batch: 12, disagree: true, label: "ALLOWED" });
    expect(toParams(f).toString()).toBe("label=ALLOWED&batch=12&disagree=1");
    expect(readFilters(new URLSearchParams("batch=x&disagree=yes"))).toEqual({});
  });
  it("says how our label compares with the dataset's", () => {
    expect(datasetVerdict("NEEDS_REVIEW", "fraud")).toBe("caught");
    expect(datasetVerdict("ALLOWED", "fraud")).toBe("missed fraud");
    expect(datasetVerdict("VIOLATING", "legitimate")).toBe("false alarm");
    expect(datasetVerdict("ALLOWED", "legitimate")).toBe("agrees");
  });
});
