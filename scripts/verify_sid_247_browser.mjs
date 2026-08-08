import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const apiKey = process.env.PCOS_VERIFY_API_KEY;
const baseUrl = process.env.PCOS_VERIFY_FRONTEND_URL || "http://127.0.0.1:3010";
const backendUrl = process.env.PCOS_VERIFY_BACKEND_URL || "http://127.0.0.1:8000";
const chromePath = process.env.PCOS_VERIFY_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDir = process.env.PCOS_VERIFY_OUTPUT_DIR || "/tmp/pcos-sid247-browser";
const reportPath = process.env.PCOS_VERIFY_REPORT || "docs/verification/SID-247-browser-report.json";

if (!apiKey) {
  throw new Error("PCOS_VERIFY_API_KEY is required");
}

const widths = [
  { width: 1440, height: 1100 },
  { width: 1024, height: 1000 },
  { width: 768, height: 1000 },
  { width: 390, height: 844 },
];

const routes = [
  { id: "today", path: "/today", heading: /today/i },
  { id: "morning", path: "/morning", heading: /evidence supports/i },
  { id: "projects", path: "/projects", heading: /projects/i },
  { id: "project-brain", path: "/projects/pcos-ai-todoist-agent", heading: /pcos|chief of staff/i },
  { id: "chat", path: "/chat", heading: /chief of staff|chat/i },
];

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--no-sandbox"],
});

await mkdir(outputDir, { recursive: true });
await mkdir(path.dirname(reportPath), { recursive: true });

const report = {
  schema_version: 1,
  scope: "SID-247 responsive and accessibility verification",
  frontend_url: baseUrl,
  backend_url: backendUrl,
  external_model_access: "disabled by verification server environment",
  raw_provider_payloads_retained: false,
  screenshots_retained_in_repository: false,
  widths: [],
};

for (const viewport of widths) {
  const context = await browser.newContext({
    viewport,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const requestFailures = [];
  const httpErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      const location = message.location();
      consoleErrors.push({ text: message.text(), url: location.url || null, line: location.lineNumber || null });
    }
  });
  page.on("requestfailed", (request) => {
    requestFailures.push({ url: new URL(request.url()).pathname, error: request.failure()?.errorText || "unknown" });
  });
  page.on("response", (response) => {
    if (response.status() >= 400) httpErrors.push({ url: new URL(response.url()).pathname, status: response.status() });
  });

  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.evaluate(({ backendUrl, apiKey }) => {
    localStorage.setItem("pcos.backendUrl", backendUrl);
    localStorage.setItem("pcos.apiKey", apiKey);
  }, { backendUrl, apiKey });

  const widthResult = { viewport, routes: [], retained_state: null, correction_dialog: null };

  for (const route of routes) {
    consoleErrors.length = 0;
    requestFailures.length = 0;
    httpErrors.length = 0;
    await page.goto(`${baseUrl}${route.path}`, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForLoadState("networkidle", { timeout: 120000 }).catch(() => undefined);

    if (route.id === "chat") {
      const input = page.getByPlaceholder("Ask your chief of staff...");
      await input.waitFor({ state: "visible", timeout: 30000 });
      await input.fill("What needs me today?");
      await page.getByRole("button", { name: "Send" }).click();
      const groundingSummary = page.getByText(/Shared reality evidence \(\d+\)/i).last();
      await groundingSummary.waitFor({ state: "visible", timeout: 120000 });
      await groundingSummary.click();
      await page.getByText(/needs today · read only/i).last().waitFor({ state: "visible", timeout: 30000 });
    }

    const metrics = await page.evaluate(() => {
      const overlay = document.querySelector("[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay");
      const headings = [...document.querySelectorAll("h1,h2,h3,h4")].filter((node) => node.getClientRects().length > 0);
      const landmarks = [...document.querySelectorAll("main,nav,header,aside,footer,[role='main'],[role='navigation']")]
        .filter((node) => node.getClientRects().length > 0);
      const disclosures = [...document.querySelectorAll("details > summary,button[aria-expanded]")]
        .filter((node) => node.getClientRects().length > 0);
      const buttons = [...document.querySelectorAll("button")].filter((node) => node.getClientRects().length > 0);
      const buttonHeights = buttons.map((node) => Math.round(node.getBoundingClientRect().height));
      return {
        has_content: document.body.innerText.trim().length > 100,
        error_overlay: Boolean(overlay),
        horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        document_scroll_height: document.documentElement.scrollHeight,
        viewport_height: document.documentElement.clientHeight,
        headings: headings.length,
        h1_count: document.querySelectorAll("h1").length,
        landmarks: landmarks.length,
        disclosures: disclosures.length,
        buttons: buttons.length,
        minimum_visible_button_height: buttonHeights.length ? Math.min(...buttonHeights) : null,
        provider_limitations_visible: /provider limitations|evidence is incomplete|some evidence is incomplete/i.test(document.body.innerText),
        read_only_grounding_visible: /Needs Today · Read Only/i.test(document.body.innerText),
        evidence_visible_without_hover: /evidence|source|provider/i.test(document.body.innerText),
      };
    });

    await page.keyboard.press("Tab");
    const focus = await page.evaluate(() => {
      const node = document.activeElement;
      if (!(node instanceof HTMLElement)) return { visible: false, tag: null };
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        visible: rect.width > 0 && rect.height > 0,
        tag: node.tagName.toLowerCase(),
        outline: style.outlineStyle,
      };
    });

    await page.screenshot({
      path: path.join(outputDir, `${viewport.width}-${route.id}.png`),
      fullPage: true,
    });

    widthResult.routes.push({
      id: route.id,
      path: route.path,
      final_url: new URL(page.url()).pathname,
      metrics,
      keyboard_focus: focus,
      console_errors: consoleErrors.filter((item) => !String(item.url || "").endsWith("/favicon.ico")),
      expected_console_noise: consoleErrors.filter((item) => String(item.url || "").endsWith("/favicon.ico")),
      request_failures: requestFailures.filter((item) => item.error !== "net::ERR_ABORTED"),
      expected_request_cancellations: requestFailures.filter((item) => item.error === "net::ERR_ABORTED"),
      unexpected_http_errors: httpErrors.filter((item) => item.status !== 503),
    });
  }

  await page.goto(`${baseUrl}/morning`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.getByRole("heading", { name: /evidence supports/i }).waitFor({ timeout: 120000 });
  let failNextMorningRead = true;
  await page.route(`${backendUrl}/morning-state`, async (route) => {
    if (failNextMorningRead) {
      failNextMorningRead = false;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "SID-247 controlled refresh failure" }) });
      return;
    }
    await route.continue();
  });
  await page.getByRole("button", { name: /refresh/i }).click();
  await page.getByText(/refresh failed; showing retained state/i).waitFor({ timeout: 30000 });
  const retainedVisible = await page.getByText(/refresh failed; showing retained state/i).isVisible();
  await page.getByRole("button", { name: /refresh/i }).click();
  await page.getByText(/refresh failed; showing retained state/i).waitFor({ state: "hidden", timeout: 120000 });
  widthResult.retained_state = { controlled_503_retained_content: retainedVisible, recovery_cleared_warning: true };

  const correctionToggle = page.getByRole("button", { name: "Correct this conclusion" }).first();
  if (await correctionToggle.isVisible().catch(() => false)) {
    await correctionToggle.click();
    const previewButton = page.getByRole("button", { name: "Preview exact provider change" }).first();
    await previewButton.click();
    const dialog = page.getByRole("dialog", { name: "Exact completion preview" });
    await dialog.waitFor({ state: "visible", timeout: 30000 });
    await dialog.locator("dl").waitFor({ state: "visible", timeout: 30000 });
    const dialogContentFits = await dialog.evaluate((node) => {
      const values = Array.from(node.querySelectorAll("dd"));
      return node.scrollWidth <= node.clientWidth && values.every((value) => value.scrollWidth <= value.clientWidth);
    });
    const focusInside = await page.evaluate(() => document.querySelector("[role='dialog']")?.contains(document.activeElement) || false);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    const focusStillInside = await page.evaluate(() => document.querySelector("[role='dialog']")?.contains(document.activeElement) || false);
    await page.screenshot({ path: path.join(outputDir, `${viewport.width}-correction-dialog.png`), fullPage: true });
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden", timeout: 30000 });
    await page.waitForFunction((node) => document.activeElement === node, await previewButton.elementHandle(), { timeout: 3000 }).catch(() => undefined);
    const focusRestored = await previewButton.evaluate((node) => document.activeElement === node);
    widthResult.correction_dialog = {
      opened: true,
      exact_preview_rendered: true,
      content_fits_without_clipping: dialogContentFits,
      focus_initially_inside: focusInside,
      focus_trap_preserved: focusStillInside,
      escape_closed: true,
      trigger_focus_restored: focusRestored,
    };
  }

  report.widths.push(widthResult);
  await context.close();
}

await browser.close();
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ report: reportPath, screenshot_dir: outputDir, widths: report.widths.length }));
