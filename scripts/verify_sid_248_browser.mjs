import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

let apiKey = process.env.PCOS_VERIFY_API_KEY;
if (!apiKey && process.env.PCOS_VERIFY_ENV_FILE) {
  const envText = await readFile(process.env.PCOS_VERIFY_ENV_FILE, "utf8");
  const match = envText.match(/^AGENT_API_KEY=(.*)$/m);
  apiKey = match?.[1]?.trim().replace(/^['"]|['"]$/g, "");
}
const frontendUrl = process.env.PCOS_VERIFY_FRONTEND_URL || "http://127.0.0.1:3110";
const backendUrl = process.env.PCOS_VERIFY_BACKEND_URL || "http://127.0.0.1:8100";
const outputDir = process.env.PCOS_VERIFY_OUTPUT_DIR || "/tmp/pcos-sid248-browser";
const reportPath = process.env.PCOS_VERIFY_REPORT || "/tmp/pcos-sid248-browser-report.json";
const chromePath = process.env.PCOS_VERIFY_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const fixturePayload = process.env.PCOS_VERIFY_FIXTURE_FILE
  ? await readFile(process.env.PCOS_VERIFY_FIXTURE_FILE, "utf8")
  : null;

if (!apiKey) throw new Error("PCOS_VERIFY_API_KEY is required");

const requestedWidths = new Set(
  (process.env.PCOS_VERIFY_WIDTHS || "")
    .split(",")
    .map((value) => Number(value.trim()))
    .filter(Boolean),
);
const viewports = [
  { width: 1440, height: 1000 },
  { width: 1024, height: 900 },
  { width: 768, height: 900 },
  { width: 390, height: 1000 },
].filter((viewport) => requestedWidths.size === 0 || requestedWidths.has(viewport.width));

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--no-sandbox"],
});
const report = { scope: "SID-248 Morning Brief product review", viewports: [] };

for (const viewport of viewports) {
  const context = await browser.newContext({ viewport, reducedMotion: "reduce" });
  const page = await context.newPage();
  const consoleErrors = [];
  const requestFailures = [];
  const httpErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    if (request.failure()?.errorText !== "net::ERR_ABORTED") {
      requestFailures.push({ url: request.url(), error: request.failure()?.errorText });
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() });
    }
  });
  if (fixturePayload) {
    await page.route(`${backendUrl}/morning-state*`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: fixturePayload }),
    );
    await page.route(`${backendUrl}/morning-corrections*`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
  }

  await page.goto(frontendUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.evaluate(({ backendUrl, apiKey }) => {
    localStorage.setItem("pcos.backendUrl", backendUrl);
    localStorage.setItem("pcos.apiKey", apiKey);
  }, { backendUrl, apiKey });
  await page.goto(`${frontendUrl}/morning`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.getByRole("heading", { level: 1 }).waitFor({ state: "visible", timeout: 120000 });
  await page.waitForLoadState("networkidle", { timeout: 120000 }).catch(() => undefined);

  const metrics = await page.evaluate(() => {
    const visibleText = document.body.innerText;
    const headings = [...document.querySelectorAll("main h2")].map((node) => node.textContent?.trim());
    const bottomNav = document.querySelector("body > div nav.fixed") ?? document.querySelector("nav.fixed");
    const bottomNavScroller = bottomNav?.firstElementChild;
    const bottomNavLinks = [...(bottomNav?.querySelectorAll("a") ?? [])];
    const navBounds = bottomNavScroller?.getBoundingClientRect();
    const primaryLabels = [...document.querySelectorAll("p")].filter((node) =>
      /^(Primary move|Review before acting)$/.test(node.textContent?.trim() || ""),
    );
    return {
      h1: document.querySelector("main h1")?.textContent?.trim(),
      h1_count: document.querySelectorAll("main h1").length,
      section_headings: headings,
      primary_label_count: primaryLabels.length,
      horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      error_overlay: Boolean(document.querySelector("[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay")),
      raw_uuid_visible: /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i.test(visibleText),
      raw_hash_visible: /\b[0-9a-f]{32,64}\b/i.test(visibleText),
      internal_terms_visible: /\b(needs_action|potential_mismatch|deterministic conclusion|canonical classification|source reconciliation)\b/i.test(visibleText),
      open_disclosures: document.querySelectorAll("details[open]").length,
      control_counts_visible: /already handled/i.test(visibleText) && /waiting or intentionally paused/i.test(visibleText),
      details_and_corrections_visible: /Details and corrections/i.test(visibleText),
      date_conflict_count: (visibleText.match(/The task title says Aug 15, but its Todoist due date says Aug 8\./g) || []).length,
      bottom_nav: {
        destination_count: bottomNavLinks.length,
        target_heights: bottomNavLinks.map((link) => Math.round(link.getBoundingClientRect().height)),
        fully_visible_labels: bottomNavLinks.map((link) => {
          const label = link.querySelector("span");
          const bounds = link.getBoundingClientRect();
          return {
            destination: link.getAttribute("aria-label"),
            link_inside_scroller: Boolean(navBounds && bounds.left >= navBounds.left - 1 && bounds.right <= navBounds.right + 1),
            label_unclipped: !label || getComputedStyle(label).display === "none" || label.scrollWidth <= label.clientWidth + 1,
          };
        }),
      },
      forbidden_default_language: [
        "classified as actionable",
        "structured due evidence",
        "today's command",
        "attributable changes",
        "selected meaningful-check boundary",
        "selected check boundary",
      ].filter((term) => visibleText.toLowerCase().includes(term)),
      body_preview: visibleText.slice(0, 500),
    };
  });

  const keyboardNav = [];
  const bottomNavLinks = page.locator("nav.fixed a");
  const bottomNavCount = await bottomNavLinks.count();
  if (bottomNavCount) {
    await bottomNavLinks.first().focus();
    for (let index = 0; index < bottomNavCount; index += 1) {
      keyboardNav.push(await page.evaluate(() => ({
        destination: document.activeElement?.getAttribute("aria-label"),
        visible: Boolean(document.activeElement && document.activeElement.getBoundingClientRect().width > 0),
      })));
      if (index < bottomNavCount - 1) await page.keyboard.press("Tab");
    }
    await page.evaluate(() => {
      (document.activeElement instanceof HTMLElement ? document.activeElement : null)?.blur();
      const scroller = document.querySelector("nav.fixed")?.firstElementChild;
      if (scroller instanceof HTMLElement) scroller.scrollLeft = 0;
    });
  }

  const screenshot = path.join(outputDir, `morning-${viewport.width}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  const evidence = page.getByText("Details and corrections", { exact: true }).first();
  const hasEvidence = await evidence.count() > 0;
  if (hasEvidence) await evidence.click();
  const evidenceReachable = hasEvidence && await page.getByText("Supporting evidence", { exact: true }).first().isVisible().catch(() => false);
  const technicalClosedByDefault = hasEvidence && !(await page.getByText("Evidence references:", { exact: false }).first().isVisible().catch(() => false));
  if (hasEvidence) await evidence.click();

  let retainedFailure = null;
  if (viewport.width === 1024 && await page.getByRole("button", { name: "Refresh" }).count() > 0) {
    let failNextRead = true;
    await page.route(`${backendUrl}/morning-state*`, async (route) => {
      if (failNextRead) {
        failNextRead = false;
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "SID-248 controlled read failure" }) });
        return;
      }
      await route.fallback();
    });
    await page.getByRole("button", { name: "Refresh" }).click();
    const warning = page.getByText(/refresh failed; showing retained state/i);
    await warning.waitFor({ state: "visible", timeout: 30000 });
    retainedFailure = {
      warning_visible: await warning.isVisible(),
      headline_retained: await page.getByRole("heading", { level: 1 }).isVisible(),
    };
  }

  report.viewports.push({
    viewport,
    screenshot,
    metrics,
    keyboard_bottom_nav: keyboardNav,
    evidence_reachable: evidenceReachable,
    technical_references_closed_by_default: technicalClosedByDefault,
    retained_failure: retainedFailure,
    console_errors: consoleErrors.filter((item) => !/(404 \(Not Found\)|503 \(Service Unavailable\))/.test(item)),
    expected_console_errors: consoleErrors.filter((item) => /(404 \(Not Found\)|503 \(Service Unavailable\))/.test(item)),
    unexpected_http_errors: httpErrors.filter((item) => item.status !== 503 && item.path !== "/favicon.ico"),
    expected_http_errors: httpErrors.filter((item) => item.status === 503 || item.path === "/favicon.ico"),
    request_failures: requestFailures,
  });
  await context.close();
}

await browser.close();
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ report: reportPath, screenshots: report.viewports.map((item) => item.screenshot) }));
