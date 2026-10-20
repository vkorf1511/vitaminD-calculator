import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/locations", async (route) => {
    await route.fulfill({
      json: [{
        country_code: "EC",
        country_name: "Ecuador",
        cities: [{ name: "Quito", latitude: -0.18, longitude: -78.47, population: 2781641 }],
      }],
    });
  });
  await page.route("**/process", async (route) => {
    await route.fulfill({
      json: {
        location: "Quito, Ecuador",
        date: "2026-10-20",
        recommendation: "You should stay under the sun for 12 minutes between 12:00 and 13:00 local time.",
        window_start: "12:00",
        window_end: "13:00",
        recommended_minutes: 12,
        hourly_exposure_minutes: Array.from({ length: 24 }, (_, hour) => hour === 12 ? 12 : 0),
        hourly_uv_index: Array(24).fill(6),
        advisory: "This is a simplified educational estimate, not medical advice.",
      },
    });
  });
});

test("shows the calculator and estimate for a selected city", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /find your sun-safe moment/i })).toBeVisible();
  await page.getByLabel("Where are you?").selectOption("EC:0");
  await page.getByRole("button", { name: /get my sun window/i }).click();
  await expect(page.getByText(/12 minutes between 12:00 and 13:00/)).toBeVisible();
  await expect(page.getByRole("img", { name: /hourly recommended exposure minutes/i })).toBeVisible();
  await expect(page.getByText(/not medical advice/i)).toBeVisible();
});

test("shows a readable error when the forecast service fails", async ({ page }) => {
  await page.route("**/process", async (route) => {
    await route.fulfill({ status: 502, json: { detail: "The weather forecast is temporarily unavailable." } });
  });
  await page.goto("/");
  await page.getByLabel("Where are you?").selectOption("EC:0");
  await page.getByRole("button", { name: /get my sun window/i }).click();
  await expect(page.getByRole("alert").filter({ hasText: /weather forecast is temporarily unavailable/i }))
    .toHaveText(/weather forecast is temporarily unavailable/i);
});
