// 🚦 客户端冒烟门 (2026-08-01 Yi: 「bug太多了」— 玩家撞到的 bug 百分之百在客户端,
// 而客户端此前一道闸都没有)。与 smoke_stories.py 同地位: 部署前必跑, 红了不许上。
//
// 干什么: 本地起一个一次性服务 (throwaway DB + MockLLM, 零成本零网络), 用 Playwright
// 把玩家金路径真点一遍 — 注册/大厅/建档/手机每个 app/返回键/手账页签/工坊/创作页 —
// 全程零 JS 报错才放行。它抓的正是这周的那类实弹: 死键、劈词、传参约定、UI 回归。
//
//     node smoke_client.js          (约 60~90s; 需要本机 playwright-core + chromium)
//
// 夹具: tests/fixtures_smoke_story.json (从服务器扒的最小已发布剧本《末班车上的陌生人》,
// 无地图 legacy 本 — 顺带压住无地图分支)。发布走真 lint 门: 夹具发不出去本身就是回归。
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

// 端口随进程号浮动: 上一跑的孤儿服务占着固定端口 = 这一跑静默连上旧代码 (实弹)
const PORT = 8200 + (process.pid % 500);
const BASE = `http://127.0.0.1:${PORT}`;
const API = `${BASE}/api/v1`;
const DB = path.join(__dirname, "smoke_client.db");
const EXE = process.env.SMOKE_CHROMIUM || path.join(
  process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1228", "chrome-win64", "chrome.exe");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const failures = [];
let checks = 0;
function ok(cond, label) {
  checks++;
  if (cond) console.log("  ✓ " + label);
  else { failures.push(label); console.log("  ✗ " + label); }
}

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
  // ── 1. 一次性服务: 新库 + MockLLM (确定性, 不花一分钱, 断网也能跑) ──
  try { fs.unlinkSync(DB); } catch (e) {}
  const py = path.join(__dirname, ".venv", "Scripts", "python.exe");
  const server = spawn(py, ["-m", "uvicorn", "app.main:app", "--port", String(PORT)], {
    cwd: __dirname,
    env: { ...process.env, DATABASE_URL: "sqlite+pysqlite:///./smoke_client.db",
           JWT_SECRET: "dev", LLM_PROVIDER: "mock", PYTHONIOENCODING: "utf-8",
           DEEPSEEK_API_KEY: "", DASHSCOPE_API_KEY: "", ARK_API_KEY: "",
           // 🪟 fcntl 垫片: Unix 锁模块在 Windows 不存在 (2026-08-01 本门首跑实弹:
           // runs.py 顶层 import fcntl, 整个应用在 dev 机起不来)
           PYTHONPATH: path.join(__dirname, "winshim")
             + (process.env.PYTHONPATH ? ";" + process.env.PYTHONPATH : "") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let srvLog = "";
  server.stdout.on("data", (d) => { srvLog += d; });
  server.stderr.on("data", (d) => { srvLog += d; });
  const kill = () => {   // Windows: 必须整棵进程树砍, 否则 uvicorn 孤儿占端口 (实弹)
    try { spawn("taskkill", ["/pid", String(server.pid), "/T", "/F"], { stdio: "ignore" }); } catch (e) {}
    try { server.kill(); } catch (e) {}
  };
  process.on("exit", kill);

  let up = false;
  for (let i = 0; i < 60; i++) {
    await sleep(1000);
    try { const r = await fetch(API + "/health"); if (r.ok) { up = true; break; } } catch (e) {}
  }
  if (!up) { console.error("服务 60s 没起来:\n" + srvLog.slice(-1200)); kill(); process.exit(2); }
  console.log("· 一次性服务已就绪 (MockLLM)");

  // ── 2. API 铺路: 注册 → 传夹具 → 发布 (发布走真 lint 门) → 建专用档 ──
  // 邮箱不能用 .local/.test 这类保留域 — email 校验器当场拒 (本门首跑实弹)
  const su = await api("POST", "/auth/signup", {
    email: "smoke@lpgate.com", password: "smokegate1", dob: "1990-01-01", accepted_tos: true });
  const setc = su.headers.get("set-cookie") || "";
  const cookie = (setc.match(/lp_session=[^;]+/) || [""])[0];
  ok(su.status < 300 && !!cookie, "注册 + 会话 cookie");

  const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "tests", "fixtures_smoke_story.json"), "utf8"));
  // 秘密入库会重铸 fragment id — 夹具里的旧引用会悬空过不了 lint; 门控引用清掉
  // (与 AI 起草的 _strip_all_gates 同法), 发现页要 public 才见得到卡
  fx.story.visibility = "public";
  for (const a of fx.story.acts || []) if (a.advance) a.advance.required_fragment_ids = [];
  for (const e of fx.story.endings || []) if (e.condition) e.condition.required_fragment_ids = [];
  const st = await api("POST", "/stories", fx.story, cookie);
  ok(st.status < 300 && st.data && st.data.id, `夹具剧本入库 (${st.status})`);
  const sid = st.data && st.data.id;
  for (const sec of fx.secrets) await api("POST", `/stories/${sid}/secrets`, sec, cookie);
  const pub = await api("POST", `/stories/${sid}/publish`, undefined, cookie);
  ok(pub.status < 300, `发布过 lint 门 (${pub.status}${pub.status === 422 ? " " + JSON.stringify((pub.data || {}).detail).slice(0, 160) : ""})`);

  const masks = await api("GET", "/personas", undefined, cookie);
  const pid = (masks.data && masks.data[0] && masks.data[0].id)
    || ((await api("POST", "/personas", { name: "冒烟员", pronouns: "they" }, cookie)).data || {}).id;
  const lead = (fx.story.characters.find((c) => c.is_lead) || fx.story.characters[0]) || {};
  const run = await api("POST", "/runs", { story_id: sid, persona_id: pid,
    mode: "character", player_character_id: null }, cookie);
  ok(run.status < 300 && run.data && run.data.id, `开档 (MockLLM 开场, ${run.status})`);
  const rid = run.data && run.data.id;

  // 服务端面: feed 首开必须立欢迎通告
  const feed = await api("GET", `/runs/${rid}/social`, undefined, cookie);
  const wp = ((feed.data || {}).posts || []).find((p) => p.welcome);
  ok(!!wp && /欢迎来到|Welcome to/.test(wp.text || ""), "📣 feed 开卷欢迎通告在位");

  // ── 3. 浏览器金路径 ──
  const { chromium } = require("playwright-core");
  const browser = await chromium.launch({ executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await ctx.addCookies([{ name: "lp_session", value: cookie.split("=")[1], domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const jsErrors = [];
  page.on("pageerror", (e) => jsErrors.push("play: " + e.message));

  await page.goto(`${BASE}/play`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => { try { localStorage.setItem("lp_tut_v1", "1"); } catch (e) {} });
  await sleep(3500);
  const lobby = await page.evaluate(() => ({
    marquee: !!document.querySelector(".mtitle") && document.querySelector(".mtitle").getBoundingClientRect().height > 0,
    doors: document.querySelectorAll(".door").length,
    cards: document.querySelectorAll(".scard").length,
  }));
  ok(lobby.marquee, "大厅刊头在位");
  ok(lobby.doors === 2, `书架/创作两扇门 (${lobby.doors})`);
  ok(lobby.cards >= 1, `剧本 hero 卡 ≥1 (${lobby.cards})`);

  // 进档 (MockLLM 开场即回)。⚠️ 发射不等待: resumeRun 的 promise 要等 VN 播放,
  // VN 播放要等玩家点击 — await 它 = 互等死锁 (实弹)
  await page.evaluate((id) => { resumeRun(id); }, rid);
  await sleep(6000);
  await page.evaluate(() => { try { closeHowto(); } catch (e) {} try { closeTutorial(); } catch (e) {} });
  // runId 是页面顶层 let, 不在 window 上 — 必须裸标识符取 (play.html 同款老坑)
  const inRun = await page.evaluate(() => !!runId);
  ok(inRun, "resumeRun 进档");

  // 手机金路径: 主屏 → 手账两页 → 返回键 → 通讯录 → 动态(欢迎卡) → 合上
  await page.evaluate(() => openPhone());
  await sleep(1200);
  ok(await page.evaluate(() => !!document.getElementById("phoneov")), "📱 手机主屏打开");
  await page.evaluate(() => openPlanner("cal"));
  await sleep(400);
  ok(await page.evaluate(() => document.querySelectorAll(".ptabs .pt").length === 2), "🗓 手账两页签");
  await page.evaluate(() => openPlanner("notes"));
  await sleep(400);
  ok(await page.evaluate(() => !!document.getElementById("noteText")), "📝 笔记页表单在位");
  const backWorks = await page.evaluate(async () => {
    const b = document.querySelector("#phoneov .pback");
    if (!b) return "无返回键";
    b.click();
    await new Promise((r) => setTimeout(r, 900));
    // 回到主屏 = papps 网格重现
    return document.querySelector("#phoneov .papps") ? "ok" : "点了没回主屏";
  });
  ok(backWorks === "ok", `‹ 返回键真的回主屏 (${backWorks})`);
  // 防呆: backTo 传光杆名字也不许死键
  const backGuard = await page.evaluate(() => {
    phoneShell("<i>x</i>", "防呆测试", "phone");
    const b = document.querySelector("#phoneov .pback");
    return b && (b.getAttribute("onclick") || "").includes("openPhone()");
  });
  ok(backGuard, "phoneShell 防呆: 光杆 backTo 归一成 openPhone()");
  await page.evaluate(() => openContacts());
  await sleep(1500);
  ok(await page.evaluate(() => document.querySelectorAll("#phoneov .pthread, #phoneov .jempty").length > 0), "👥 通讯录渲染");
  await page.evaluate(() => openSocial());
  await sleep(1500);
  const wpUi = await page.evaluate(() => (document.getElementById("phoneov") || {}).innerText || "");
  ok(/欢迎来到|Welcome to/.test(wpUi), "📣 欢迎通告渲染进动态");
  await page.evaluate(() => { const o = document.getElementById("phoneov"); if (o) o.remove(); });

  // 纯函数探针: 这周的两类实弹永不复发
  const probes = await page.evaluate(() => {
    const en = paginate("First sentence here. Second one follows. Mr. Duna waits.");
    const zh = paginate("他站在门口很久没有说话。手里那把刀转得越来越慢了！");   // 两句都>6字, 不触发碎屑并页
    return { enPages: en.length, enNoSplitWord: en.every((p) => !/[a-z]$/.test(p) || / /.test(p)),
             abbrSafe: en.some((p) => p.includes("Mr. Duna")), zhPages: zh.length };
  });
  ok(probes.enPages === 3 && probes.abbrSafe, `西文分页按句成页+缩写不劈 (${probes.enPages})`);
  ok(probes.zhPages === 2, `中文分页回归 (${probes.zhPages})`);

  // 工坊 + 创作页
  const p2 = await ctx.newPage();
  p2.on("pageerror", (e) => jsErrors.push("studio: " + e.message));
  await p2.goto(`${BASE}/studio`, { waitUntil: "domcontentloaded" });
  await sleep(2500);
  const studio = await p2.evaluate(() => {
    story = blankStory(); story.language = "en"; openEditor();
    const vis = (el) => !!el && el.getBoundingClientRect().height > 0;
    const tab = [...document.querySelectorAll("#secTabs *")].find((t) => /角色/.test(t.textContent));
    if (tab) tab.click();
    document.querySelector("details[data-sec=chars]").open = true;
    return { lang: (document.getElementById("f_lang") || {}).value,
             quick: vis(document.getElementById("quickChar")) };
  });
  ok(studio.lang === "en", "工坊语言选择器读到 en");
  ok(studio.quick, "⚡ 一句话加角色入口在位");

  const p3 = await ctx.newPage();
  p3.on("pageerror", (e) => jsErrors.push("maker: " + e.message));
  await p3.goto(`${BASE}/maker`, { waitUntil: "domcontentloaded" });
  await sleep(2000);
  const maker = await p3.evaluate(() => {
    setOut("engine");
    return (document.getElementById("engineOnly") || {}).style.display !== "none"
      && !!document.getElementById("dLang");
  });
  ok(maker, "创作页引擎本模式露出演出语言");

  // 🎨 外观调节台 (?ui=1)。测三件事: 开得出来、拧了【界面真的变】、关掉之后调过的样子留着。
  // 中间那条最要紧 —— 面板最容易变成"拖了没反应"的摆设 (那正是 Yi 骂 UI 的起点)。
  const p4 = await ctx.newPage();
  p4.on("pageerror", (e) => jsErrors.push("ui: " + e.message));
  await p4.goto(`${BASE}/play?ui=1`, { waitUntil: "domcontentloaded" });
  await sleep(1500);
  const ui = await p4.evaluate(() => {
    const box = document.getElementById("uibox");
    if (!box) return { open: false };
    const R = document.documentElement;
    const before = getComputedStyle(R).getPropertyValue("--ui-font").trim();
    const rng = box.querySelector('input[type=range][data-k="--ui-font"]');
    const col = box.querySelector('input[type=color][data-k="--gold"]');
    rng.value = "21"; rng.dispatchEvent(new Event("input"));
    col.value = "#ff0000"; col.dispatchEvent(new Event("input"));
    const after = getComputedStyle(R).getPropertyValue("--ui-font").trim();
    // 真的传导到那块字上了吗 (不是只改了变量)
    const t = document.getElementById("vntext");
    const px = t ? parseFloat(getComputedStyle(t).fontSize) : 0;
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem("lp_theme") || "{}"); } catch (e) {}
    return { open: true, before, after, px, gold: stored["--gold"],
             tokens: box.querySelectorAll("input").length };
  });
  ok(ui.open, "🎨 外观调节台开得出来");
  ok(ui.before !== ui.after && ui.after === "21px", `🎨 拧字号真的改了 token (${ui.before}→${ui.after})`);
  ok(ui.px === 21, `🎨 而且传导到正文上 (#vntext = ${ui.px}px)`);
  ok(ui.gold === "#ff0000", "🎨 改过的值存住了 (刷新不丢)");
  ok(ui.tokens >= 25, `🎨 可调项 ${ui.tokens} 个`);

  ok(jsErrors.length === 0, "全程零 JS 报错" + (jsErrors.length ? "  →  " + jsErrors.slice(0, 4).join(" | ") : ""));

  await browser.close();
  kill();
  try { fs.unlinkSync(DB); } catch (e) {}
  console.log(`\n${checks - failures.length}/${checks} 项通过` + (failures.length ? `\n❌ 红灯: ${failures.join("; ")}` : "\n✅ 客户端冒烟门放行"));
  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.error("HARNESS FAIL:", e.stack || e.message); process.exit(2); });
