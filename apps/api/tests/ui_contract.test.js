// 🧪 UI 契约回归 (node --test, 零浏览器)。守 2026-08-02 体检修掉的三件事,
// 免得有人把它们改回去没人拦。
//
// 验红方式 (TDD 纪律: 没看过红的测试不算测试): 这些修复已经上线, 直接跑必绿 —
// 所以每条都用【修复前的旧片段】当红样本先验一次, 证明测试真在守, 而不是空转。
//     node --test tests/ui_contract.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const PLAY = fs.readFileSync(
  path.join(__dirname, "..", "app", "static", "play.html"), "utf8");

/** 取一条 CSS 规则的声明块 (选择器要精确到唯一). */
function rule(src, selector) {
  const i = src.indexOf(selector + " {");
  assert.ok(i >= 0, `没找到 CSS 规则: ${selector}`);
  return src.slice(i, src.indexOf("}", i));
}

/** 断言一个规则守住了 44px 热区; checker 同时用于红样本自验。 */
function has44(block) {
  return /min-height:\s*44px/.test(block) || /min-width:\s*44px/.test(block);
}

// ── 👆 触控热区 ≥44 (体检实测: 顶栏图标 26×23, 删档钮 26×19) ────────────────
const TOUCH_RULES = [
  ".iconbtn",          // 顶栏图标群
  "header .iconbtn",   // 窄屏覆盖 — 曾在这里被压回 2px padding
  ".stub .ops a",      // 存档删除/隐藏
  ".ppeek",            // 通讯录看手机
  "button.ghost",      // ← 剧本 / 合上 等次要按钮
  "#logoutBtn",        // 退出 (文字链但坐在按钮堆里)
  ".pcalrow .chk",     // 手账筹码
];

for (const sel of TOUCH_RULES) {
  test(`触控热区: ${sel} 守住 44px`, () => {
    assert.ok(has44(rule(PLAY, sel)),
      `${sel} 没有 min-width/min-height:44px — 手指按不准 (体检 2026-08-02)`);
  });
}

test("红样本自验: 旧的 .iconbtn 定义会被这条断言抓住", () => {
  // 修复前的真实定义 (git 4f60356 之前)
  const before = ".iconbtn { background: transparent; padding: 5px 7px; font-size: 16px; color: #c9bfa9; ";
  assert.equal(has44(before), false, "断言对旧代码不报红 = 这测试是空转的");
});

// ── 🔤 玩家在读的小字 ≥12px (体检: 大厅 72 处 <12px) ──────────────────────
const TEXT_RULES = [
  ".door span",           // 两扇门的说明
  ".stub .sub",           // 存根副标题
  ".stub .faces .where",  // 存根场景名
  ".castitem small",      // 在场条角色名
  ".papp small",          // 手机 app 名
];

for (const sel of TEXT_RULES) {
  test(`可读字号: ${sel} ≥12px`, () => {
    const m = rule(PLAY, sel).match(/font-size:\s*([\d.]+)px/);
    assert.ok(m, `${sel} 没有 font-size`);
    assert.ok(parseFloat(m[1]) >= 12,
      `${sel} 是 ${m[1]}px — 玩家真在读的文字不该小于 12px`);
  });
}

test("红样本自验: 旧的 11px 会被抓住", () => {
  const before = ".door span { display: block; margin-top: 4px; font-size: 11.5px; ";
  const px = parseFloat(before.match(/font-size:\s*([\d.]+)px/)[1]);
  assert.ok(px < 12, "红样本本身就该 <12, 否则这条测试没意义");
});

// ── ⏱ 界面反馈动效 ≤300ms (氛围类不在此列) ────────────────────────────────
test("toast 退场是反馈不是演出: ≤300ms", () => {
  const block = rule(PLAY, ".toast.out");
  const durs = [...block.matchAll(/([\d.]+)s/g)].map((m) => parseFloat(m[1]) * 1000);
  assert.ok(durs.length, "没找到 transition 时长");
  for (const ms of durs) {
    assert.ok(ms <= 300, `toast 退场 ${ms}ms — 微交互超 300ms 就是拖沓感`);
  }
  assert.ok(!/transition:\s*all/.test(block),
    "别用 transition:all — 会连 transform 一起拖住 (体检实弹)");
});

test("红样本自验: 旧的 .55s all 会被抓住", () => {
  const before = ".toast.out { opacity:0; transform:translateY(-8px); transition:all .55s ease; ";
  const ms = parseFloat(before.match(/([\d.]+)s/)[1]) * 1000;
  assert.ok(ms > 300 && /transition:\s*all/.test(before),
    "红样本应同时踩中两条 (>300ms 且用了 all)");
});

// ── 📱 设备名判定中英通吃 (体检截图: 英文本子标题成了「📮 phone」) ─────────
test("英文本子的手机走小手机皮, 不落信箱分支", () => {
  const i = PLAY.indexOf("const _modern =");
  assert.ok(i > 0, "没找到设备名判定");
  // ⚠️ 抓两行就够 (数组字面量 + .includes 那行)。别去匹配 "].includes" —— 源码里
  //    中间隔着换行和缩进, 匹配不上会抓出空串, 看着像产品坏了。
  //    (本周第四次栽在抓取器上; 抓不到东西先怀疑抓法, 别怀疑产品。)
  const line = PLAY.slice(i, PLAY.indexOf(";", i) + 1);
  assert.ok(line.length > 40, `抓取失败, 只拿到 ${line.length} 字符`);
  // 直接取源码里的白名单, 断言它同时含中英
  assert.ok(line.includes('"手机"'), "白名单缺中文「手机」");
  assert.ok(line.includes('"phone"'), "白名单缺英文 phone — 英文本子会落信箱皮");
  assert.ok(/toLowerCase\(\)/.test(line), "没做大小写归一, Phone 会漏网");
});

test("红样本自验: 旧的中文字面量判定会被抓住", () => {
  const before = 'phoneShell(inner, phoneDevice === "手机" ? "📱 小手机" : `📮 ${phoneDevice}`);';
  assert.ok(!before.includes('"phone"'), "红样本本身就不该含英文白名单");
});
