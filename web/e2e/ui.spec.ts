import { expect, test, type Page } from "@playwright/test";

// The seeded fixtures (tests/fixtures/postings.jsonl): 14 postings labeled by the fake backend,
// one analyst decision on fx-fee, and draft v2 tested but not published.
test.describe.configure({ mode: "serial" });

async function actAs(page: Page, user: "viewer" | "editor" | "publisher_a" | "publisher_b") {
  await page.getByLabel("Acting as").selectOption(user);
}

async function openJob(page: Page, jobId: string) {
  await page.goto(`/?job_id=${jobId}`);
  await page.locator("tbody tr").first().getByRole("link").click();
  await expect(page.locator(".doc h1")).toBeVisible();
}

test("browse lists the labels and filters by chip, kept in the URL", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("tbody tr")).toHaveCount(14);
  // every section of the policy is a filter, also one no posting matches (§3, 0)
  await expect(page.locator(".filters .chip", { hasText: "§3" })).toContainText("0");
  await expect(page.locator(".filters .chip", { hasText: /§\d/ })).toHaveCount(5);
  await page.getByRole("button", { name: /VIOLATING/ }).click();
  await expect(page).toHaveURL(/label=VIOLATING/);
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await page.reload();
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await page.getByRole("button", { name: /VIOLATING/ }).click(); // off again
  await expect(page.locator("tbody tr")).toHaveCount(14);
  await page.getByLabel("Search job id").fill("fx-pay");
  await page.getByLabel("Search job id").press("Enter");
  await expect(page.locator("tbody tr")).toHaveCount(1);
});

test("a decision highlights its verified quote in the section's colour", async ({ page }) => {
  await openJob(page, "fx-fee");
  const mark = page.locator('mark[data-section="§1"]');
  await expect(mark).toContainText("registration fee of $120");
  await expect(page.getByTestId("analyst-decision")).toContainText("needs review");
  await expect(page.locator(".finding.matched")).toContainText("§1");
});

test("the step timeline shows each node of the run", async ({ page }) => {
  await openJob(page, "fx-fee");
  const steps = page.getByTestId("steps").locator("li");
  await expect(steps).toHaveCount(6);
  await expect(steps.first()).toContainText("Cleaned");
  await expect(steps.last()).toContainText("Label set");
});

test("posting text that looks like HTML is shown as text and never runs", async ({ page }) => {
  await openJob(page, "fx-script");
  await expect(page.locator(".doc")).toContainText("<script>window.pwned=1</script>");
  expect(await page.evaluate(() => (window as any).pwned)).toBeUndefined();
});

test("an injection is held for review and the checks say why", async ({ page }) => {
  await openJob(page, "fx-injection");
  await expect(page.locator(".verdict .badge")).toHaveText("NEEDS REVIEW");
  await expect(page.locator(".checks")).toContainText("tries to give instructions to an AI");
  await expect(page.getByTestId("why")).toContainText("It tries to instruct an AI");
});

test("when the API is down the page says so", async ({ page }) => {
  await page.route("**/ui/labels?**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Can't reach the API");
});

test("the list comes in pages, kept in the URL; a filter goes back to page 1", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/^1–14 of 14/)).toBeVisible();
  await page.getByLabel("Rows per page").selectOption("10");
  await expect(page.getByText(/^1–10 of 14/)).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(10);
  await page.getByRole("button", { name: "Next →" }).first().click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByText(/^11–14 of 14/)).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await page.reload();
  await expect(page.locator("tbody tr")).toHaveCount(4); // the page survives a reload
  await page.getByRole("button", { name: /ALLOWED/ }).first().click();
  await expect(page).not.toHaveURL(/page=2/); // a filter goes back to page 1
});

test("each row shows its evidence, and a policy match opens its quote and reasoning", async ({ page }) => {
  await page.goto("/?job_id=fx-fee");
  await expect(page.getByTestId("evidence-preview")).toContainText("registration fee of $120");
  await page.getByRole("button", { name: /§1 .*show the evidence/ }).click();
  const popover = page.getByRole("dialog", { name: "§1 evidence" });
  await expect(popover).toContainText("registration fee of $120");
  await expect(popover).toContainText("Open posting");
  await page.keyboard.press("Escape");
  await expect(popover).toBeHidden();
});

test("clicking a row opens the posting; back to the list keeps the filter; next posting steps through", async ({ page }) => {
  await page.goto("/?label=NEEDS_REVIEW");
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(6);
  await rows.nth(0).locator("td.why").click(); // a cell, not the title link
  await expect(page).toHaveURL(/\/labels\/\d+/);
  const first = page.url();
  await page.getByRole("link", { name: "Next posting →" }).click();
  await expect(page).not.toHaveURL(first);
  await page.getByRole("link", { name: "← Back to the list" }).click();
  await expect(page).toHaveURL(/label=NEEDS_REVIEW/);
});

test("what the agent found links both ways with the highlights in the posting", async ({ page }) => {
  await openJob(page, "fx-fee");
  const found = page.getByTestId("found");
  await expect(found.getByRole("heading")).toHaveText("What the Labeling Agent found");
  await expect(found.locator(".finding.matched")).toContainText("registration fee of $120");
  await expect(page.getByTestId("why")).toContainText("Violates §1");
  await found.getByRole("button", { name: /registration fee/ }).click();
  await expect(page.locator('mark[data-section="§1"]').first()).toHaveClass(/flash/);
  await page.locator('mark[data-section="§1"]').first().click(); // and back: the highlight shows its section
  await expect(found.locator(".finding.matched")).toHaveClass(/flash/);
  await page.getByText("The API's answer (JSON)").click();
  await expect(page.getByTestId("api-answer")).toContainText('"job_id": "fx-fee"');
});

test("a policy section opens to its full text", async ({ page }) => {
  await page.goto("/versions/v1");
  await expect(page.getByTestId("section-§1")).toBeHidden();
  await page.getByRole("button", { name: "Open all sections" }).click();
  await expect(page.getByTestId("section-§1")).toContainText("Jev's question");
  await expect(page.getByTestId("section-§1")).toContainText("Counts as yes");
});

test("roles on a draft: a viewer reads, an editor submits, an editing publisher can't publish, another can", async ({ page }) => {
  await page.goto("/versions/v2");
  await actAs(page, "viewer");
  await expect(page.getByText("Viewers can read drafts")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0);

  await actAs(page, "editor");
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0); // editors submit, not publish
  await page.getByRole("button", { name: "Submit for publishing" }).click();
  await expect(page.getByText("Submitted. A publisher needs to publish it.")).toBeVisible();
  await page.goto("/versions");
  await expect(page.locator("tr", { hasText: "v2" })).toContainText("waiting for a publisher");

  await page.goto("/versions/v2");
  await actAs(page, "publisher_a");
  await page.getByRole("button", { name: "Save" }).first().click(); // Pat edits the draft
  await expect(page.getByText(/^Saved\./)).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toBeDisabled();
  await expect(page.getByTestId("publish-blocked")).toContainText("You edited this draft");

  await actAs(page, "publisher_b");
  await expect(page.getByTestId("flip-report")).toContainText("Test passed.");
  await expect(page.getByTestId("test-scope")).toContainText("Publish labels the 14 recent postings again");
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(page.getByText(/^Published\./)).toBeVisible();
  // The Test labeled all 14, so Publish kept them and ran nothing.
  await expect(page.getByTestId("relabel")).toContainText("All 14 recent postings are labeled under v2. 14 kept from the Test, 0 labeled again");
  await expect(page.getByTestId("relabel-panel")).toContainText("v2: all 14 recent postings re-labeled, 14 kept from the Test");
  // Without reloading the page, the header and the side panel show v2 as latest and live.
  await expect(page.getByTestId("viewing")).toContainText("Showing policy v2 (live)");
  await expect(page.getByRole("button", { name: "Compare v1 → v2" })).toBeEnabled();
  await page.goto("/versions");
  await expect(page.locator("tr", { hasText: "v2" }).locator(".status").first()).toHaveText("live");
  await expect(page.getByTestId("viewing")).toContainText("v2");
});

test("the side panel folds, shows an older version without changing what is live, and compares versions", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Hide the workspace" }).click();
  await expect(page.getByRole("complementary", { name: "Side panel" })).toBeHidden();
  await page.getByRole("button", { name: "Show the workspace" }).click();
  await expect(page.getByRole("complementary", { name: "Side panel" })).toBeVisible();
  // the same with the shortcut, like Cursor's secondary sidebar
  await page.keyboard.press("ControlOrMeta+Alt+KeyB");
  await expect(page.getByRole("complementary", { name: "Side panel" })).toBeHidden();
  await page.keyboard.press("ControlOrMeta+Alt+KeyB");
  await expect(page.getByRole("complementary", { name: "Side panel" })).toBeVisible();

  // the list's filters hide too; the list keeps its filter, and the hidden toggle shows a dot
  await page.getByRole("button", { name: "NEEDS REVIEW" }).click();
  await page.getByRole("button", { name: "Hide the filters" }).click();
  await expect(page.getByLabel("Search job id")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Show the filters" })).toHaveClass(/has-dot/);
  await page.keyboard.press("ControlOrMeta+KeyB");
  await expect(page.getByLabel("Search job id")).toBeVisible();
  // and their right edge drags wider
  const filters = page.locator(".filters-col");
  const before = (await filters.boundingBox())!.width;
  const edge = (await page.getByRole("separator", { name: "Resize the filters" }).boundingBox())!;
  await page.mouse.move(edge.x + 3, edge.y + 40);
  await page.mouse.down();
  await page.mouse.move(edge.x + 83, edge.y + 40, { steps: 4 });
  await page.mouse.up();
  expect((await filters.boundingBox())!.width).toBeGreaterThan(before + 60);
  await page.getByRole("button", { name: "NEEDS REVIEW" }).click();

  await page.getByLabel("Policy shown").selectOption("v1");
  await expect(page.getByTestId("viewing")).toContainText("Showing policy v1 · live is v2");
  await expect(page.getByText(/labels under v1/)).toBeVisible();
  await page.getByLabel("Policy shown").selectOption("v2");
  await expect(page.getByTestId("viewing")).toContainText("Showing policy v2 (live)");

  await page.getByRole("button", { name: "Compare v1 → v2" }).click();
  await expect(page.getByRole("heading", { name: "How labels changed from v1 to v2" })).toBeVisible();
  const rows = page.getByTestId("compare").locator("tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Senior Pipeline Engineer");
  await page.getByText("Only postings that changed").click();
  await expect(rows).toHaveCount(14);

  // Any two published versions can be picked on the page.
  await page.getByLabel("Compare from").selectOption("v2");
  await expect(page.getByText("Choose two different versions.")).toBeVisible();
  await page.getByLabel("Compare to").selectOption("v1");
  await expect(page.getByRole("heading", { name: "How labels changed from v2 to v1" })).toBeVisible();
  await expect(page).toHaveURL(/from=v2&to=v1/);
});

test("an editor discards a draft; published versions have no discard", async ({ page }) => {
  await page.goto("/versions");
  await actAs(page, "editor");
  await page.getByRole("button", { name: /^Create a draft from v2/ }).click();
  await expect(page.getByRole("heading", { name: /Policy v3/ })).toBeVisible();
  await page.getByRole("button", { name: "Discard this draft" }).click();
  await expect(page.getByText("Discard v3? It has no Test labels. This can't be undone.")).toBeVisible();
  await page.getByRole("button", { name: "Discard", exact: true }).click();
  await expect(page.getByText("Draft v3 discarded.")).toBeVisible();
  await expect(page.locator("tr", { hasText: "v3" })).toHaveCount(0);
  await page.goto("/versions/v2");
  await expect(page.getByRole("button", { name: "Discard this draft" })).toHaveCount(0);
});

// Last: it adds postings. It needs the dataset CSV (make demo downloads it; CI doesn't have it).
test("the live demo sends real postings, follows the run, and compares with the dataset", async ({ page, request }) => {
  const health = await (await request.get("/health")).json();
  test.skip(!health.demo?.enabled || !health.demo?.dataset, "needs DEMO_MODE and the dataset CSV");
  await page.goto("/");
  await actAs(page, "editor");
  const panel = page.getByTestId("live-run");
  await panel.getByLabel("How many postings to send").selectOption("10");
  await panel.getByRole("button", { name: "Send 10 postings" }).click();
  const result = page.getByTestId("run-result");
  await expect(result).toContainText("all 10 labeled", { timeout: 30_000 });
  await expect(result).toContainText(/Caught \d+ of [1-9]\d* fraud/); // 25% fraud: at least one sent

  await result.getByRole("button", { name: "Show this run in the list" }).click();
  await expect(page).toHaveURL(/batch=\d+/);
  await expect(page.getByTestId("run-scope")).toContainText("all 10 labeled");
  await expect(page.locator("tbody tr")).toHaveCount(10);

  await page.locator(".listbar").getByText("Compare with the dataset's label").click(); // the list's own switch
  await expect(page.getByTestId("dataset-summary")).toContainText("10 postings with a dataset label");
  await expect(panel.getByRole("checkbox", { name: "Compare with the dataset's label" })).toBeChecked(); // one setting
  await expect(page.locator("td.dataset-cell").first()).toContainText(/fraud|legitimate/);
  await page.locator("tbody tr").first().locator("td.why").click();
  await expect(page.getByTestId("dataset-line")).toContainText("The dataset marks this posting as");
  await page.getByText("Compare with the dataset's label").click(); // off again: the page looks like production
  await expect(page.getByTestId("dataset-line")).toHaveCount(0);
});
