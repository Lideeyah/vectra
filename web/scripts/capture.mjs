/**
 * The demo capture. One command, one MP4, no hands.
 *
 * Frames, not a screen recording. Every shot is composed as PNG frames and
 * assembled by ffmpeg at an exact frame count, so the timings are the contract
 * rather than whatever the machine felt like doing — a voiceover recorded
 * against these marks will still line up next week.
 *
 * ASSERT BEFORE RECORDING. Each shot states what must be on screen and the run
 * exits non-zero naming anything missing. A capture that films an empty panel
 * is worse than no capture: it looks like the product does nothing.
 *
 * Nothing here fabricates. Every figure comes from the deployed interface, the
 * explorer, or a command that actually ran.
 */
import { chromium } from "playwright";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdirSync, rmSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import path from "node:path";

const run = promisify(execFile);

// web/scripts/ -> repo root
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const OUT = path.join(ROOT, "data/demo");
const FRAMES = path.join(OUT, "frames");
const PROFILE = path.join(ROOT, "tools/capture/.profile");
const MP4 = path.join(OUT, "vectra-demo.mp4");

const SITE = process.env.VECTRA_SITE ?? "https://vectra-market.vercel.app";
const OWNER = "0x2F45E637920Cc7C7BE15130ab49224C989572AD8";
const CONTRACT = "0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0";
const EXPLORER = "https://www.oklink.com/x-layer";
/**
 * The verified-source page is Sourcify, not OKLink.
 *
 * OKLink's source tab is empty: verifying there needs an OK-ACCESS-KEY this
 * project does not have. Sourcify holds a real verification of the same
 * address — exact_match on BOTH creation and runtime bytecode, meaning the
 * published sources compile to bytes identical to what is deployed. Filming
 * OKLink's unverified page and calling it verified would be the one thing this
 * whole build has refused to do.
 */
const SOURCE_PAGE =
  `https://repo.sourcify.dev/contracts/full_match/196/${"0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0"}/`;
const FPS = 30;
const W = 1920, H = 1080;
/**
 * The viewport IS the frame: 1920x1080, the same aspect as the output.
 *
 * Earlier versions screenshotted individual elements, whose shapes are nothing
 * like 16:9, then scaled them into a 16:9 frame and padded the difference.
 * That is what produced a thick black box around the video. Capturing the
 * viewport instead means every still already fills the frame edge to edge, and
 * assembly is a straight copy rather than a fit-and-pad.
 *
 * Elements larger than the viewport are handled by zooming the PAGE down until
 * they fit, which keeps them whole and still fills the frame.
 */
const VW = 1920, VH = 1080;
/** Space between the subject and the frame edge, in page pixels. */
const MARGIN = 56;

const problems = [];
function need(ok, what) { if (!ok) problems.push(what); return ok; }

let frameNo = 0;
const timeline = [];   // { file, frames }

/**
 * Re-render ONE shot without re-recording the film.
 *
 *   ./scripts/capture.sh --only convergence
 *
 * Each shot's stills are remembered in a manifest, so fixing a bad twelve
 * seconds costs twelve seconds of capture instead of three minutes of it.
 * Without the flag everything is captured fresh.
 */
const ONLY = (process.argv.find((a) => a.startsWith("--only")) ?? "")
  .replace(/^--only[= ]?/, "") || null;
const MANIFEST = path.join(OUT, "shots.json");
const cached = existsSync(MANIFEST)
  ? JSON.parse(readFileSync(MANIFEST, "utf8")) : {};
const manifest = {};

async function shot(name, fn) {
  if (ONLY && ONLY !== name && cached[name]?.length
      && cached[name].every((e) => existsSync(e.file))) {
    manifest[name] = cached[name];
    timeline.push(...cached[name]);
    console.log(`  reusing ${name} (${cached[name].length} still(s))`);
    return;
  }
  const from = timeline.length;
  await fn();
  manifest[name] = timeline.slice(from);
  console.log(`  captured ${name} (${manifest[name].length} still(s))`);
}

/** One still, held for `seconds`. */
async function hold(page, seconds, { clip } = {}) {
  const file = path.join(FRAMES, `f${String(frameNo++).padStart(5, "0")}.png`);
  await page.screenshot({ path: file, clip });
  timeline.push({ file, frames: Math.round(seconds * FPS) });
}

/** Motion: one frame per step, `seconds` spread across them. */
async function motion(page, seconds, steps, fn) {
  const per = Math.max(1, Math.round((seconds * FPS) / steps));
  for (let i = 0; i < steps; i++) {
    await fn(i);
    const file = path.join(FRAMES, `f${String(frameNo++).padStart(5, "0")}.png`);
    await page.screenshot({ path: file });
    timeline.push({ file, frames: per });
  }
}

/**
 * Freeze anything that ticks.
 *
 * The page re-renders elapsed text every second. A frame captured mid-tick
 * shows a different number from its neighbour, which reads as a glitch in a
 * still sequence.
 */
async function freeze(page) {
  // Consent banners are hidden, never accepted. Clicking Accept would make a
  // privacy choice on the owner's behalf; hiding it only keeps browser chrome
  // out of a shot that is supposed to be one idea.
  await page.addStyleTag({ content: `
    [class*="cookie" i], [class*="consent" i], [id*="cookie" i], [id*="consent" i],
    [class*="privacy" i][class*="banner" i] { display: none !important; }
  `}).catch(() => {});
  await page.addStyleTag({ content: `
    *, *::before, *::after { animation: none !important; transition: none !important; }
    ::-webkit-scrollbar { display: none; }
  `});
}

/**
 * Frame one element, filling the viewport.
 *
 * The page is zoomed so the subject fits with a margin, then the VIEWPORT is
 * captured — already 16:9, so assembly never has to pad it into bars. Two
 * earlier approaches failed here: a CSS transform on a clone, which overflowed
 * and clipped the leading digits off the hero; and an element screenshot,
 * which was the right pixels but the wrong shape and letterboxed.
 */
async function shotOf(page, selector, seconds) {
  // Zoom the page so the subject fills the frame, then shoot the VIEWPORT.
  // The result is already 16:9, so nothing is scaled into bars afterwards.
  await page.evaluate(() => { document.documentElement.style.zoom = "1"; });
  const el = page.locator(selector).first();
  await el.scrollIntoViewIfNeeded();

  let box = await el.boundingBox();
  if (box) {
    const z = Math.min(
      (VH - MARGIN * 2) / box.height,
      (VW - MARGIN * 2) / box.width,
    );
    // Only ever zoom DOWN to fit, or UP to fill a small subject — but never so
    // far up that a short element turns into a wall of type.
    const zoom = Math.max(0.35, Math.min(z, 1.9));
    await page.evaluate((v) => { document.documentElement.style.zoom = String(v); }, zoom);
    await page.waitForTimeout(220);
    await el.scrollIntoViewIfNeeded();
    box = await el.boundingBox();
    if (box) {
      // Centre it vertically in the frame.
      await page.evaluate(({ y, h, vh }) => window.scrollBy(0, y - (vh - h) / 2),
        { y: box.y, h: box.height, vh: VH });
      await page.waitForTimeout(150);
    }
  }

  const file = path.join(FRAMES, `f${String(frameNo++).padStart(5, "0")}.png`);
  await page.screenshot({ path: file });
  timeline.push({ file, frames: Math.round(seconds * FPS) });
  await page.evaluate(() => { document.documentElement.style.zoom = "1"; });
}

/**
 * A full-frame card of plain text, for the title and the terminal.
 *
 * The body is the flex container and it is exactly one viewport tall. An
 * earlier version centred a child with height:100% inside a min-height body —
 * a percentage height against an auto-height parent resolves to nothing, so
 * the title sat at the top of the frame instead of its middle.
 */
async function card(page, html, seconds) {
  await page.setContent(`<!doctype html><meta charset="utf-8">
  <style>
    html { height: 100%; }
    body {
      margin: 0; height: 100vh; background: #000; color: #fff;
      font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
      display: flex; align-items: center; justify-content: center;
      box-sizing: border-box; padding: 72px;
    }
    .title { font-size: 64px; letter-spacing: -0.01em; text-align: center; }
    pre {
      margin: 0; font-size: 22px; line-height: 1.5; white-space: pre-wrap;
      width: 100%; align-self: center;
    }
    .ok { color: #4ade80; } .dim { color: #94a3b8; }
  </style>${html}`);
  await page.waitForTimeout(120);
  await hold(page, seconds);
}

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

async function main() {
  // Only wipe when recording everything; a targeted re-render needs the
  // other shots' stills to still be there.
  if (!ONLY) rmSync(FRAMES, { recursive: true, force: true });
  mkdirSync(FRAMES, { recursive: true });
  // Start numbering past whatever already exists so a re-render cannot
  // overwrite a still another shot is still pointing at.
  frameNo = ONLY ? Date.now() % 90000 : 0;
  mkdirSync(PROFILE, { recursive: true });

  // THE COMMAND RUNS FOR REAL, and before anything is filmed, so a failing
  // test stops the capture rather than being cut around.
  console.log("running the blast-radius test for real…");
  let testOut = "";
  try {
    // The whole cap group: one test proves a reverting leg is not charged,
    // the other that a sell does not refund headroom. Together they are "the
    // loss stops at the cap"; either alone is half of it.
    const r = await run("forge", ["test", "--match-test", "test_Cap_", "-vv"],
      { cwd: ROOT, maxBuffer: 1 << 24 });
    testOut = r.stdout;
  } catch (e) {
    testOut = `${e.stdout ?? ""}${e.stderr ?? ""}`;
  }
  need(/\[PASS\]/.test(testOut) && /CapExceeded|Suite result: ok/.test(testOut),
       "blast-radius test did not pass (shot 2:00)");

  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: false,
    viewport: { width: VW, height: VH },
    deviceScaleFactor: 1,
    args: [`--window-size=${VW},${VH}`, "--hide-scrollbars"],
  });
  const page = ctx.pages()[0] ?? await ctx.newPage();
  page.setDefaultTimeout(45000);

  const app = `${SITE}/?owner=${OWNER}`;

  // ---- data the shots depend on, asserted from the live site -------------
  await page.goto(app, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);
  await freeze(page);

  const facts = await page.evaluate(() => ({
    hero: document.querySelector("[data-testid=distance-hero]")?.innerText ?? "",
    rows: document.querySelectorAll("[data-testid=convergence-row]").length,
    legs: [...document.querySelectorAll("[data-testid=leg-row]")].map((n) => n.innerText),
    refusals: document.querySelectorAll("[data-testid=refusal-row]").length,
    proof: [...document.querySelectorAll("[data-testid=proof-row]")].map((n) => n.innerText),
    chartPts: [...document.querySelectorAll("[data-testid=distance-chart] polyline")]
      .reduce((a, p) => a + p.getAttribute("points").trim().split(/\s+/).length, 0),
    cap: document.querySelector("[data-testid=cap-spent]")?.innerText ?? "",
    rate: document.querySelector("[data-testid=rule-rate-value]")?.innerText ?? "",
  }));

  need(facts.hero && facts.hero !== "—%", "distance hero is empty (shot 0:40)");
  need(facts.rows >= 1, "no convergence rows (shot 0:40)");
  need(facts.legs.length >= 1, "no executed legs on the site (shot 2:30)");
  need(facts.legs.some((t) => /0x[0-9a-f]{64}/i.test(t)),
       "no leg shows a transaction hash (shot 2:30)");
  need(facts.refusals >= 1, "refusal log is empty (shot 2:30)");
  need(facts.proof.some((t) => t.includes(CONTRACT)),
       `contract address ${CONTRACT} not visible in the proof rows (shot 1:35)`);
  need(facts.chartPts > 1, `distance series has ${facts.chartPts} plotted point(s), needs >1 (shot 2:30)`);
  need(facts.cap.includes("/"), "cap bar shows no spent/total (shot 1:05)");
  need(facts.rate && facts.rate !== "—", "rate bound renders as a dash (shot 1:05)");

  const legHash = (facts.legs.join(" ").match(/0x[0-9a-f]{64}/i) ?? [])[0];

  // ---- 0:00 title --------------------------------------------------------
  await shot("title", async () => {
    await card(page, `<div class="title">A twenty two cent trade.</div>`, 3);
  });

  // ---- 0:03 the executed leg on the explorer -----------------------------
  await shot("tx", async () => {
    if (legHash) {
      await page.goto(`${EXPLORER}/tx/${legHash}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(9000);
      await freeze(page);
      const shown = await page.evaluate((h) => document.body.innerText.includes(h.slice(0, 20)), legHash);
      need(shown, `explorer did not render tx ${legHash} (shot 0:03)`);
      await hold(page, 17);
    } else {
      await card(page, `<pre>no executed leg to show</pre>`, 17);
    }
  });

  // ---- 0:20 the cycle log -------------------------------------------------
  await shot("cyclelog", async () => {
    await page.goto(app, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(9000);
    await freeze(page);
    await page.evaluate(() => document.querySelector("[data-testid=refusals]")
      ?.scrollIntoView({ block: "start" }));
    await motion(page, 20, 40, async (i) => {
      await page.evaluate((n) => window.scrollBy(0, n === 0 ? 0 : 14), i);
    });
  });

  // ---- 0:40 convergence ---------------------------------------------------
  await shot("convergence", async () => {
    await shotOf(page, "[data-testid=convergence]", 25);
  });

  // ---- 1:05 the mandate ---------------------------------------------------
  await shot("mandate", async () => {
    await shotOf(page, "[data-testid=rules]", 30);
  });

  // ---- 1:35 proof, then the source page -----------------------------------
  await shot("proof", async () => {
    await shotOf(page, "[data-testid=proof]", 13);

    await page.goto(SOURCE_PAGE, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);
    await freeze(page);
    const src = await page.evaluate(() => document.body.innerText);
    need(/metadata\.json/i.test(src) && /sources/i.test(src),
         "Sourcify has no verified sources for this address (shot 1:35)");
    await hold(page, 12);
  });

  // ---- 2:00 rules and the cap, then the test running ----------------------
  await shot("capandtest", async () => {
    await page.goto(app, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(9000);
    await freeze(page);
    await shotOf(page, "[data-testid=rules]", 8);

    // 22s over 22 steps: one frame-run per second, so the rounding in motion()
    // divides evenly instead of losing a third of a second.
    const lines = testOut.trimEnd().split("\n").slice(-22);
    await motion(page, 22, Math.min(lines.length, 22), async (i) => {
      const body = esc(lines.slice(0, i + 1).join("\n"))
        .replace(/(\[PASS\][^\n]*)/g, '<span class="ok">$1</span>');
      await page.setContent(`<!doctype html><meta charset="utf-8"><style>
        html,body{margin:0;height:100%;background:#000;color:#e2e8f0;
          font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;}
        pre{margin:0;padding:56px;font-size:24px;line-height:1.5;white-space:pre-wrap;}
        .ok{color:#4ade80;}</style><pre>$ forge test --match-test test_Cap_ -vv\n\n${body}</pre>`);
    });
  });

  // ---- 2:30 legs, refusals, chart -----------------------------------------
  await shot("evidence", async () => {
    await page.goto(app, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(9000);
    await freeze(page);
    await shotOf(page, "[data-testid=legs]", 8);
    await shotOf(page, "[data-testid=refusals]", 6);
    await shotOf(page, "[data-testid=distance-chart]", 6);
  });

  // ---- 2:50 the contract, held ---------------------------------------------
  await shot("contract", async () => {
    await page.goto(`${EXPLORER}/address/${CONTRACT}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(9000);
    await freeze(page);
    await hold(page, 10);
  });

  await ctx.close();

  if (problems.length) {
    console.error("\nNOT RECORDED — these shots would have been empty or false:");
    for (const p of problems) console.error(`  - ${p}`);
    process.exit(1);
  }

  // ---- assemble ------------------------------------------------------------
  // Land on the contract exactly. Rounding inside the motion shots can leave
  // the sequence a frame or two short, and a mark that drifts is a voiceover
  // that drifts with it — so the final hold absorbs the difference.
  const TARGET_FRAMES = 180 * FPS;
  let total = timeline.reduce((a, t) => a + t.frames, 0);
  if (total !== TARGET_FRAMES) {
    const adjust = TARGET_FRAMES - total;
    timeline[timeline.length - 1].frames += adjust;
    console.log(`final hold adjusted by ${adjust} frame(s) to land on 3:00`);
    total = TARGET_FRAMES;
  }
  const intended = total / FPS;
  console.log(`intended duration ${intended.toFixed(2)}s across ${timeline.length} stills`);

  // The concat demuxer plus a variable-rate encode drifts: the stated
  // durations are honoured loosely and the result ran 10s long, which moves
  // every mark a voiceover is written against. Constant frame rate, and the
  // stream is cut to the intended length so the contract holds exactly.
  const list = timeline
    .map((t) => `file '${t.file}'\nduration ${(t.frames / FPS).toFixed(4)}`)
    .join("\n") + `\nfile '${timeline[timeline.length - 1].file}'\n`;
  writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2));

  const listFile = path.join(OUT, "frames.txt");

  // NORMALISE FIRST.
  //
  // The concat demuxer needs every input to be the same size. These stills are
  // not: a full-page capture is 2560x1720 and an element capture is whatever
  // the element measures. Feeding both in scrambled which still appeared when
  // — the video showed the rules block during the convergence shot. Each frame
  // is scaled to fit 1920x1080 and padded, so nothing is cropped and every
  // input is identical in size before it is concatenated.
  console.log(`normalising ${timeline.length} stills to ${W}x${H}…`);
  for (const t of timeline) {
    const norm = t.file.replace(/\.png$/, ".n.png");
    await run("ffmpeg", ["-y", "-v", "error", "-i", t.file, "-vf",
      // Every still is already 1920x1080. This only guarantees it, and costs
      // nothing when the input already matches.
      `scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H}`, norm]);
    t.file = norm;
  }

  writeFileSync(listFile, timeline
    .map((t) => `file '${t.file}'\nduration ${(t.frames / FPS).toFixed(4)}`)
    .join("\n") + `\nfile '${timeline[timeline.length - 1].file}'\n`);

  await run("ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", listFile,
    "-vf", `fps=${FPS}`,
    "-fps_mode", "cfr", "-r", String(FPS), "-t", intended.toFixed(3),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
    "-an", MP4], { maxBuffer: 1 << 26 });

  const probe = await run("ffprobe", ["-v", "error", "-show_entries", "format=duration",
    "-of", "default=nk=1:nw=1", MP4]);
  const secs = parseFloat(probe.stdout.trim());
  console.log(`\n${MP4}`);
  // Round to whole seconds FIRST: 179.93 formatted the naive way prints 2:60.
  const whole = Math.round(secs);
  console.log(`duration ${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")} `
            + `(${secs.toFixed(2)}s), ${W}x${H}, ${FPS}fps, no audio`);
}

main().catch((e) => { console.error(e); process.exit(1); });
