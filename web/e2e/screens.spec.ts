import { test } from "@playwright/test";

// Screenshots of each page at desktop and phone width, for review (test-results/screens).
for (const [name, width, height] of [["desktop", 1440, 900], ["phone", 390, 844]] as const) {
  test(`screenshots at ${name} width`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.locator("tbody tr").first().waitFor();
    await page.screenshot({ path: `test-results/screens/${name}-browse.png`, fullPage: true });
    await page.goto("/?job_id=fx-fee");
    await page.locator("tbody tr").first().getByRole("link").click();
    await page.getByTestId("steps").locator("li").first().waitFor();
    await page.screenshot({ path: `test-results/screens/${name}-decision.png`, fullPage: true });
    await page.goto("/versions/v2");
    await page.locator(".editor").waitFor();
    await page.screenshot({ path: `test-results/screens/${name}-version.png`, fullPage: true });
  });
}
