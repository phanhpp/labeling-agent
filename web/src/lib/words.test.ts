import { describe, expect, it } from "vitest";
import { field, location, modelName, reason, reasonSentence, stepName } from "./words";

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
