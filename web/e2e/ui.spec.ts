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
  await expect(page.locator(".rail")).toContainText("seems to give instructions to an AI");
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
  await rows.nth(0).locator("td").nth(4).click(); // a cell, not the title link
  await expect(page).toHaveURL(/\/labels\/\d+/);
  const first = page.url();
  await page.getByRole("link", { name: "Next posting →" }).click();
  await expect(page).not.toHaveURL(first);
  await page.getByRole("link", { name: "← Back to the list" }).click();
  await expect(page).toHaveURL(/label=NEEDS_REVIEW/);
});

test("the evidence card shows the quotes and takes you to each one in the posting", async ({ page }) => {
  await openJob(page, "fx-fee");
  const evidence = page.getByTestId("evidence");
  await expect(evidence).toContainText("registration fee of $120");
  await evidence.getByRole("button", { name: /registration fee/ }).click();
  await expect(page.locator('mark[data-section="§1"]').first()).toHaveClass(/flash/);
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

test("roles: a viewer can't edit, an editor can't publish, an editing publisher can't publish, another can", async ({ page }) => {
  await page.goto("/versions/v2");
  await actAs(page, "viewer");
  await page.getByRole("button", { name: "Save" }).first().click();
  await expect(page.getByText("This user's role can't do that.")).toBeVisible();

  await actAs(page, "editor");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("This user's role can't do that.")).toBeVisible();

  await actAs(page, "publisher_a");
  await page.getByRole("button", { name: "Save" }).first().click(); // Pat edits the draft
  await expect(page.getByText(/^Saved\./)).toBeVisible();
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("You edited this draft, so a different publisher has to publish it.")).toBeVisible();

  await actAs(page, "publisher_b");
  await expect(page.getByTestId("flip-report")).toContainText("Test passed.");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText(/^Published\./)).toBeVisible();
  await page.goto("/versions");
  await expect(page.locator("tr", { hasText: "v2" }).locator(".status")).toHaveText("live");
  await expect(page.locator(".pill")).toContainText("v2");
});
