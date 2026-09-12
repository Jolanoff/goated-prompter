import { test, expect } from "@playwright/test";

const key = "goated-prompter.saved-prompts.v1";
const record = (id) => ({
  id,
  title: id,
  prompt: "  Exact text\n",
  createdAt: "2026-09-09T00:00:00.000Z",
  target: "Flux",
});

test("retry after a committed POST with a lost response saves exactly one record", async ({
  page,
  request,
}) => {
  const attempts = [];
  await page.route("**/api/prompts", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts.push(route.request().postDataJSON());
    if (attempts.length === 1) {
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      await route.abort();
    } else await route.continue();
  });
  try {
    await page.goto("/");
    await page
      .getByLabel("Generated prompt", { exact: true })
      .fill("  Retry exactly\n");
    await page
      .getByRole("button", { name: "Save Prompt", exact: true })
      .click();
    await page.getByLabel("Prompt name").fill("Lost response retry");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
      "Could not save",
    );
    const committed = await (await request.get("/api/prompts")).json();
    expect(
      committed.prompts.filter((item) => item.title === "Lost response retry"),
    ).toEqual([attempts[0]]);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    expect(attempts).toHaveLength(2);
    expect(attempts[1]).toEqual(attempts[0]);
    const retried = await (await request.get("/api/prompts")).json();
    expect(
      retried.prompts.filter((item) => item.title === "Lost response retry"),
    ).toEqual([attempts[0]]);
    await page.getByRole("button", { name: /Saved Prompts/ }).click();
    await expect(
      page.getByRole("heading", { name: "Lost response retry", exact: true }),
    ).toHaveCount(1);
  } finally {
    for (const { id } of attempts)
      await request.delete(`/api/prompts/${id}`, { data: {} });
  }
});

for (const failure of [
  "conflict",
  "malformed browser",
  "inexact response",
  "offline",
  "inaccessible browser",
]) {
  test(`legacy migration retains browser data on ${failure}, then imports without duplicates`, async ({
    page,
    request,
  }) => {
    const server = record(`server-${failure.replaceAll(" ", "-")}`);
    const legacy = record(`legacy-${failure.replaceAll(" ", "-")}`);
    expect((await request.post("/api/prompts", { data: server })).ok()).toBe(
      true,
    );
    if (failure === "conflict")
      await request.post("/api/prompts", {
        data: { ...legacy, prompt: "conflicting text" },
      });
    const raw =
      failure === "malformed browser" ? "[{}]" : JSON.stringify([legacy]);
    try {
      await page.goto("/");
      await expect(page.getByText("Local backend connected")).toBeVisible();
      await page.getByRole("button", { name: /Saved Prompts/ }).click();
      await expect(
        page.getByRole("heading", { name: server.title, exact: true }),
      ).toBeVisible();
      await page.evaluate(({ key, raw }) => localStorage.setItem(key, raw), {
        key,
        raw,
      });
      if (failure === "inexact response") {
        await page.route("**/api/prompts/import", (route) =>
          route.fulfill({
            json: { prompts: [{ ...legacy, prompt: "trimmed" }] },
          }),
        );
      } else if (failure === "offline") {
        await page.route("**/api/prompts/import", (route) => route.abort());
      } else if (failure === "inaccessible browser") {
        await page.addInitScript(() => {
          const getItem = Storage.prototype.getItem;
          Storage.prototype.getItem = function (key) {
            if (key === "goated-prompter.saved-prompts.v1")
              throw new Error("Access denied");
            return getItem.call(this, key);
          };
        });
      }
      await page.reload();
      await page.getByRole("button", { name: /Saved Prompts/ }).click();
      await expect(page.getByRole("alert")).toContainText(
        "Browser data has been kept",
      );
      await expect(
        page.getByRole("heading", { name: server.title, exact: true }),
      ).toBeVisible();
      expect(await page.evaluate((key) => localStorage[key], key)).toBe(raw);
      await page.unrouteAll();
      if (failure === "inaccessible browser") return;
      if (failure === "conflict")
        await request.delete(`/api/prompts/${legacy.id}`, { data: {} });
      await page.evaluate(
        ({ key, legacy }) =>
          localStorage.setItem(key, JSON.stringify([legacy])),
        { key, legacy },
      );
      for (let reload = 0; reload < 3; reload++) {
        await page.reload();
        await page.getByRole("button", { name: /Saved Prompts/ }).click();
        await expect(
          page.getByRole("heading", { name: legacy.title, exact: true }),
        ).toHaveCount(1);
        await expect(
          page.getByRole("heading", { name: server.title, exact: true }),
        ).toBeVisible();
        expect(
          await page.evaluate((key) => localStorage.getItem(key), key),
        ).toBeNull();
        const data = await (await request.get("/api/prompts")).json();
        expect(data.prompts.filter((item) => item.id === legacy.id)).toEqual([
          legacy,
        ]);
        // Simulate another tab retaining the same old copy: import must be idempotent.
        if (reload === 0)
          await page.evaluate(
            ({ key, legacy }) =>
              localStorage.setItem(key, JSON.stringify([legacy])),
            { key, legacy },
          );
      }
    } finally {
      await request.delete(`/api/prompts/${encodeURIComponent(server.id)}`, {
        data: {},
      });
      await request.delete(`/api/prompts/${encodeURIComponent(legacy.id)}`, {
        data: {},
      });
    }
  });
}

test("offline startup retry loads prompts; save and delete failures preserve UI state", async ({
  page,
  request,
}) => {
  let offline = true;
  await page.route("**/api/bootstrap", (route) =>
    offline ? route.abort() : route.continue(),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Retry connection" }),
  ).toBeVisible();
  offline = false;
  await page.getByRole("button", { name: "Retry connection" }).click();
  await page
    .getByLabel("Generated prompt", { exact: true })
    .fill("  Save exactly\n");
  let releaseLoad;
  const gate = new Promise((resolve) => {
    releaseLoad = resolve;
  });
  await page.route("**/api/prompts", async (route) => {
    if (route.request().method() === "POST") {
      await gate;
      await route.fulfill({ status: 500, json: { error: "Disk unavailable" } });
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Save Prompt", exact: true }).click();
  await page.getByLabel("Prompt name").fill("Async persistence");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByLabel("Prompt name")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Close save dialog" }),
  ).toBeDisabled();
  releaseLoad();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "Disk unavailable",
  );
  await expect(page.getByLabel("Prompt name")).toHaveValue("Async persistence");
  await page.unroute("**/api/prompts");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: /Saved Prompts/ }).click();
  const data = await (await request.get("/api/prompts")).json();
  const saved = data.prompts.find((item) => item.title === "Async persistence");
  try {
    expect(saved.prompt).toBe("  Save exactly\n");
    await page.route("**/api/prompts/*", (route) =>
      route.fulfill({ status: 500, json: { error: "Cannot write file" } }),
    );
    page.on("dialog", (dialog) => dialog.accept());
    await page
      .getByRole("button", { name: "Delete Async persistence" })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "Could not delete prompt",
    );
    await expect(
      page.getByRole("heading", { name: "Async persistence" }),
    ).toBeVisible();
    await page.unroute("**/api/prompts/*");
    await page
      .getByRole("button", { name: "Delete Async persistence" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Async persistence" }),
    ).toHaveCount(0);
  } finally {
    if (saved) await request.delete(`/api/prompts/${saved.id}`, { data: {} });
  }
});

test("initial prompt load gates saving and can be retried independently", async ({
  page,
}) => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api/prompts", async (route) => {
    await gate;
    await route.fulfill({
      status: 503,
      json: { error: "Temporarily offline" },
    });
  });
  await page.goto("/");
  await page
    .getByLabel("Generated prompt", { exact: true })
    .fill("Waiting for disk");
  await expect(
    page.getByRole("button", { name: "Save Prompt", exact: true }),
  ).toBeDisabled();
  release();
  await expect(page.getByRole("alert")).toContainText(
    "Could not load saved prompts",
  );
  await page.unroute("**/api/prompts");
  await page.getByRole("button", { name: "Retry saved prompts" }).click();
  await expect(
    page.getByRole("button", { name: "Save Prompt", exact: true }),
  ).toBeEnabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
