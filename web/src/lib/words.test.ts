import { describe, expect, it } from "vitest";
import { dollars, field, plural, location, modelName, reason, reasonSentence, relabelSentence, stepName } from "./words";

describe("plain words", () => {
  it("puts reason codes into a sentence", () => {
    expect(reason("section_unsure")).toBe("Claude was unsure about a section");
    expect(reasonSentence(["review_section_matched", "section_unsure"])).toBe(
      "A section that sends postings to review matched and Claude was unsure about a section.",
    );
    expect(reasonSentence([])).toBe("");
    expect(reason("something_new")).toBe("something new");
  });

  it("names fields, steps and models the way people say them", () => {
    expect(field("company_profile")).toBe("company profile");
    expect(field("company_logo")).toBe("logo");
    expect(stepName("escalate")).toBe("Claude read it");
    expect(modelName("jev_sonnet;escalate=claude-sonnet-5-5;screen=jev;agent=2;prompt=p1")).toBe("Jev + Claude Sonnet 5.5");
    expect(modelName("sonnet_only;escalate=claude-sonnet-5-5;screen=none;agent=2;prompt=p1")).toBe("Claude Sonnet 5.5");
    expect(modelName("fake;sonnet_only;escalate=claude-sonnet-5-5")).toBe("the sample stand-in (no AI model)");
  });

  it("drops the empty parts of a location", () => {
    expect(location("GB, , London")).toBe("GB, London");
    expect(location("US, NY, New York")).toBe("US, NY, New York");
    expect(location(undefined)).toBe("");
  });
});

describe("re-label progress", () => {
  const base = { kept_from_test: 25, relabeled: 40, in_code: 0, waiting: 35, total: 100, cost_usd: 0.16 };
  it("says what was kept, labeled and is waiting", () => {
    expect(relabelSentence("v2", base)).toBe(
      "Labeling recent postings again under v2: 65 of 100 done. 25 kept from the Test, 40 labeled again, 35 waiting. Cost so far $0.16.",
    );
  });
  it("says when it is finished, and what was decided in code", () => {
    expect(relabelSentence("v4", { ...base, kept_from_test: 0, relabeled: 100, in_code: 100, waiting: 0, cost_usd: 0 })).toBe(
      "All 100 recent postings are labeled under v4. 0 kept from the Test, 100 labeled again (100 decided in code at $0). Cost $0.00.",
    );
  });
  it("writes small costs plainly", () => {
    expect(dollars(0.004)).toBe("under $0.01");
    expect(dollars(0.3)).toBe("$0.30");
  });
});

describe("plural", () => {
  it("adds an s except for one", () => {
    expect(plural(1, "false alarm")).toBe("1 false alarm");
    expect(plural(0, "false alarm")).toBe("0 false alarms");
    expect(plural(3, "posting")).toBe("3 postings");
  });
});
