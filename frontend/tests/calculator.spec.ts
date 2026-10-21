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

test("saves the email signup with the selected profile and shows confirmation", async ({ page }) => {
  let receivedSignup: Record<string, unknown> | undefined;
  await page.route("**/email_list", async (route) => {
    receivedSignup = route.request().postDataJSON();
    await route.fulfill({
      json: {
        id: 1,
        email_address: "alex@example.com",
        name: "Alex",
        skin_type: "IV",
        location: { name: "Quito, Ecuador", latitude: -0.18, longitude: -78.47 },
        timezone: -5,
      },
    });
  });
  await page.goto("/");
  await page.getByLabel("Where are you?").selectOption("EC:0");
  await page.getByLabel("Skin type").selectOption("IV");
  await page.getByLabel("Your name").fill("Alex");
  await page.getByLabel("Email address").fill("alex@example.com");
  await page.getByRole("button", { name: "Sign me up" }).click();

  await expect(page).toHaveURL(/\/successful_submission\/?$/);
  await expect(page.getByRole("heading", { name: /your signup was successful/i })).toBeVisible();
  await expect(page.getByText(/automatically in/i)).toContainText("7");
  expect(receivedSignup).toMatchObject({
    email_address: "alex@example.com",
    name: "Alex",
    skin_type: "IV",
    latitude: -0.18,
    longitude: -78.47,
    location_name: "Quito, Ecuador",
  });
});

test("returns to the main app from the signup confirmation page", async ({ page }) => {
  await page.goto("/successful_submission");
  await page.getByRole("link", { name: "Return to the main app" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: /find your sun-safe moment/i })).toBeVisible();
});

test("automatically returns to the main app after seven seconds", async ({ page }) => {
  await page.goto("/successful_submission");
  await expect(page).toHaveURL("/", { timeout: 10_000 });
});
