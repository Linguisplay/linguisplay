// 📱 小手机 UI 体检 (Yi 2026-08-06:「优化一下手机页面的ui，先检查一下」)。
// 起一次性服务 → 进档 → 逐页截图 + 量真实尺寸。只看不改。
//   node inspect_phone.js
// 产出: scratchpad/phone/*.png + 一份量出来的清单
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const PORT = 8700 + (process.pid % 200);
const BASE = `http://127.0.0.1:${PORT}`;
const API = `${BASE}/api/v1`;
const DB = path.join(__dirname, "inspect_phone.db");
const OUT = process.env.PHONE_OUT || path.join(__dirname, "_phone_shots");
const EXE = process.env.SMOKE_CHROMIUM || path.join(
  process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1228", "chrome-win64", "chrome.exe");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(method, p, body, cookie) {
  const r = await fetch(API + p, {
    method,
    headers: { "Content-Type": "application/json", ...(cookie ? { Cookie: cookie } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await r.json(); } catch (e) {}
  return { status: r.status, data, headers: r.headers };
}

(async () => {
  try { fs.unlinkSync(DB); } catch (e) {}
  fs.mkdirSync(OUT, { recursive: true });
  const py = path.join(__dirname, ".venv", "Scripts", "python.exe");
  const server = spawn(py, ["-m", "uvicorn", "app.main:app", "--port", String(PORT)], {
    cwd: __dirname,
    env: { ...process.env, DATABASE_URL: "sqlite+pysqlite:///./inspect_phone.db",
           JWT_SECRET: "dev", LLM_PROVIDER: "mock", PYTHONIOENCODING: "utf-8",
           DEEPSEEK_API_KEY: "", DASHSCOPE_API_KEY: "", ARK_API_KEY: "",
           PYTHONPATH: path.join(__dirname, "winshim")
             + (process.env.PYTHONPATH ? ";" + process.env.PYTHONPATH : "") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let log = "";
  server.stdout.on("data", (d) => { log += d; });
  server.stderr.on("data", (d) => { log += d; });
  const done = () => { try { server.kill(); } catch (e) {} };
  process.on("exit", done);

  for (let i = 0; i < 60; i++) {
    await sleep(500);
    try { const r = await fetch(`${BASE}/api/v1/health`); if (r.ok) break; } catch (e) {}
    if (i === 59) { console.log("服务起不来:\n" + log.slice(-1500)); process.exit(1); }
  }

  // 铺路照抄 smoke_client.js：cookie 名 lp_session，夹具要 public + 清门控引用才发得出去
  const su = await api("POST", "/auth/signup", {
    email: `insp${process.pid}@lpgate.com`, password: "inspect1234",
    dob: "1990-01-01", accepted_tos: true });
  const cookie = ((su.headers.get("set-cookie") || "").match(/lp_session=[^;]+/) || [""])[0];
  if (!cookie) { console.log("注册失败:", su.status, JSON.stringify(su.data)); process.exit(1); }
  const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "tests", "fixtures_smoke_story.json"), "utf8"));
  fx.story.visibility = "public";
  for (const a of fx.story.acts || []) if (a.advance) a.advance.required_fragment_ids = [];
  for (const e of fx.story.endings || []) if (e.condition) e.condition.required_fragment_ids = [];
  const st = await api("POST", "/stories", fx.story, cookie);
  const sid = (st.data || {}).id;
  for (const sec of fx.secrets || []) await api("POST", `/stories/${sid}/secrets`, sec, cookie);
  const pub = await api("POST", `/stories/${sid}/publish`, undefined, cookie);
  if (pub.status >= 300) { console.log("发布失败:", pub.status, JSON.stringify(pub.data)); process.exit(1); }
  const masks = await api("GET", "/personas", undefined, cookie);
  const pid = (masks.data && masks.data[0] && masks.data[0].id)
    || ((await api("POST", "/personas", { name: "阿妍", pronouns: "they" }, cookie)).data || {}).id;
  const run = await api("POST", "/runs", { story_id: sid, persona_id: pid,
    mode: "character", player_character_id: null }, cookie);
  const rid = (run.data || {}).id;

  const { chromium } = require("playwright-core");
  const browser = await chromium.launch({ executablePath: EXE });
  const errs = [];

  // 三种真机尺寸: 小屏 SE / 主流 14Pro / 大屏 ProMax
  const SIZES = [["se", 375, 667], ["pro", 390, 844], ["max", 430, 932]];
  const REPORT = {};

  for (const [tag, w, h] of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h },
                                           isMobile: true, hasTouch: true,
                                           deviceScaleFactor: 2 });
    await ctx.addCookies([{ name: "lp_session", value: cookie.split("=")[1],
                            domain: "127.0.0.1", path: "/" }]);
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errs.push(`${tag}: ${e.message}`));
    await page.goto(`${BASE}/play`, { waitUntil: "domcontentloaded" });
    await page.evaluate(() => { try { localStorage.setItem("lp_tut_v1", "1"); } catch (e) {} });
    await sleep(2500);
    await page.evaluate((id) => { resumeRun(id); }, rid);
    await sleep(3500);
    // 开场那两张卡 (#tutov 教程 / #howto 进故事) 会盖住手机 —— 先关干净再拍
    await page.evaluate(() => {
      try { closeTutorial(); } catch (e) {}
      try { closeHowto(); } catch (e) {}
      ["tutov", "howto"].forEach((id) => { const e = document.getElementById(id); if (e) e.style.display = "none"; });
    });
    await sleep(600);
    await page.evaluate(() => openPhone());
    await sleep(900);
    await page.screenshot({ path: path.join(OUT, `${tag}-01-home.png`) });

    // 📏 量主屏: 图标网格、触控靶、状态栏、Dock
    REPORT[tag] = await page.evaluate(() => {
      const r = (el) => el ? el.getBoundingClientRect() : null;
      const ov = document.getElementById("phoneov");
      const icons = [...document.querySelectorAll("#phoneov .papp")];
      const boxes = icons.map((e) => { const b = e.getBoundingClientRect();
        return { t: Math.round(b.top), l: Math.round(b.left),
                 w: Math.round(b.width), h: Math.round(b.height),
                 label: (e.textContent || "").trim().slice(0, 6) }; });
      // 每行的 top 值应当一致; 列间距应当均匀
      const rows = {};
      boxes.forEach((b) => { rows[b.t] = (rows[b.t] || []).concat([b.l]); });
      const rowKeys = Object.keys(rows).map(Number).sort((a, b2) => a - b2);
      const colGaps = rowKeys.length ? rows[rowKeys[0]].sort((a, b2) => a - b2)
        .map((v, i, arr) => (i ? +(v - arr[i - 1]).toFixed(1) : null)).filter((x) => x !== null) : [];
      // 触控靶 < 44 的
      const small = boxes.filter((b) => b.w < 44 || b.h < 44);
      return {
        overlay: r(ov) && { w: Math.round(r(ov).width), h: Math.round(r(ov).height) },
        iconCount: boxes.length,
        rows: rowKeys.length,
        rowTops: rowKeys,
        colGaps,
        smallTargets: small,
        iconSize: boxes[0] ? { w: boxes[0].w, h: boxes[0].h } : null,
      };
    });

    // 逐个二级页: 点进去截图 + 量返回键与标题
    const APPS = [["msg", "信息"], ["feed", "动态"], ["contacts", "通讯录"],
                  ["album", "回忆"], ["notes", "手账"]];
    for (const [key, label] of APPS) {
      const hit = await page.evaluate((lb) => {
        const el = [...document.querySelectorAll("#phoneov .papp")]
          .find((e) => (e.textContent || "").includes(lb));
        if (!el) return false;
        el.click(); return true;
      }, label);
      if (!hit) { REPORT[tag][key] = "找不到入口"; continue; }
      await sleep(700);
      await page.screenshot({ path: path.join(OUT, `${tag}-${key}.png`) });
      REPORT[tag][key] = await page.evaluate(() => {
        // 📏 导航栏三件套的垂直中心 + 触控靶 + 页面死区
        const ov = document.getElementById("phoneov");
        const all = [...ov.querySelectorAll("*")];
        const byTxt = (re) => all.find((e) => re.test((e.textContent || "").trim())
          && e.children.length === 0);
        const mid = (e) => { const b = e.getBoundingClientRect();
          return { cy: +(b.top + b.height / 2).toFixed(1), w: Math.round(b.width),
                   h: Math.round(b.height), top: Math.round(b.top) }; };
        const back = byTxt(/^‹\s*返回$|^返回$/);
        const shut = byTxt(/^合上$/);
        const titl = [...ov.querySelectorAll("b, strong, .ptitle, h3")]
          .find((e) => (e.textContent || "").trim().length &&
                       e.getBoundingClientRect().top < 400);
        // 最后一个有内容的元素之后, 到手机底之间的空白
        const shell = ov.querySelector("div");
        const sb = shell ? shell.getBoundingClientRect() : null;
        let lowest = 0;
        all.forEach((e) => { const b = e.getBoundingClientRect();
          if (b.height > 0 && b.width > 0 && (e.textContent || "").trim()) lowest = Math.max(lowest, b.bottom); });
        const NAV = {
          back: back ? mid(back) : null,
          title: titl ? mid(titl) : null,
          shut: shut ? mid(shut) : null,
          deadSpace: sb ? Math.round(sb.bottom - lowest) : null,
          shellH: sb ? Math.round(sb.height) : null,
        };
        const nav = document.querySelector("#phoneov .pnav, #phoneov .ptitle");
        const backBtn = [...document.querySelectorAll("#phoneov button, #phoneov .pback")]
          .find((b) => /‹|返回|<|back/i.test(b.textContent || ""));
        const bb = backBtn ? backBtn.getBoundingClientRect() : null;
        const body = document.querySelector("#phoneov .pbody, #phoneov .pscroll");
        // 对比度粗查: 正文色 vs 背景色
        const probe = document.querySelector("#phoneov .pbody *, #phoneov .pscroll *");
        const cs = probe ? getComputedStyle(probe) : null;
        return {
          NAV,
          hasNav: !!nav,
          back: bb ? { w: Math.round(bb.width), h: Math.round(bb.height),
                       tooSmall: bb.width < 44 || bb.height < 44 } : "无返回键",
          bodyTop: body ? Math.round(body.getBoundingClientRect().top) : null,
          color: cs ? cs.color : null, bg: cs ? cs.backgroundColor : null,
          fontSize: cs ? cs.fontSize : null,
        };
      });
      await page.evaluate(() => openPhone());
      await sleep(500);
    }
    await ctx.close();
  }

  console.log(JSON.stringify({ REPORT, errs }, null, 1));
  await browser.close();
  done();
  process.exit(0);
})();
