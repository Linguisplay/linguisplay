// 🧪 工坊手机端契约 (node --test)。Yi 报障 2026-08-02:「手机端看不见编辑剧本里的内容」。
// 真机复现: 内容其实都在 DOM 里, 但长文 textarea 只有 54px (两行), 世界观/梗概/开场白
// 被切在半句; 页签换行占 119px, 第一屏几乎全是控件。
//
// 验红方式: 每条都用【修复前的真实旧片段】自验, 保证断言不会退化成空转。
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(
  path.join(__dirname, "..", "app", "static", "studio.html"), "utf8");

function rule(src, selector) {
  const i = src.indexOf(selector + " {");
  assert.ok(i >= 0, `没找到 CSS 规则: ${selector}`);
  return src.slice(i, src.indexOf("}", i));
}

// ── 📝 长文框要给得下一段话 ───────────────────────────────────────────────
test("textarea 至少能显示 4 行 (长文框不许把世界观切在半句)", () => {
  const block = rule(SRC, "textarea");
  const m = block.match(/min-height:\s*(\d+)px/);
  assert.ok(m, "textarea 没有 min-height");
  const px = parseInt(m[1], 10);
  // 15px 字号 × 1.6 行高 ≈ 24px/行, 加 20px 内边距; 4 行 ≈ 116px
  assert.ok(px >= 110,
    `textarea min-height 只有 ${px}px ≈ ${Math.round((px - 20) / 24)} 行 — 长文看不全`);
});

test("红样本自验: 旧的 54px 会被抓住", () => {
  const before = "textarea { resize: vertical; min-height: 54px; ";
  const px = parseInt(before.match(/min-height:\s*(\d+)px/)[1], 10);
  assert.ok(px < 110, "红样本本身就该不达标, 否则这条测试没意义");
});

// ── 🗂 页签栏不许吃掉第一屏 ───────────────────────────────────────────────
test("页签栏横向滚动, 不换行堆高", () => {
  const block = rule(SRC, ".sectabs");
  assert.ok(/overflow-x:\s*auto/.test(block),
    "页签栏要能横向滑 — 换行会堆成三排吃掉第一屏 (真机实测 119px)");
  assert.ok(!/flex-wrap:\s*wrap/.test(block),
    ".sectabs 不该 flex-wrap:wrap");
  assert.ok(/white-space:\s*nowrap|flex-shrink:\s*0/.test(SRC.slice(
    SRC.indexOf(".sectabs {"), SRC.indexOf(".sectabs {") + 600)),
    "页签按钮要 flex-shrink:0, 否则横滑时会被压扁");
});

test("红样本自验: 旧的 wrap 布局会被抓住", () => {
  const before = ".sectabs { display:none; position:sticky; top:0; flex-wrap:wrap; ";
  assert.ok(/flex-wrap:\s*wrap/.test(before) && !/overflow-x:\s*auto/.test(before),
    "红样本应同时踩中两条");
});

// ── 📱 手机顶栏不许折行 ───────────────────────────────────────────────────
test("工坊顶栏有手机适配 (标题不折成两行)", () => {
  assert.ok(/@media\s*\(max-width:\s*\d+px\)/.test(SRC),
    "studio.html 没有任何手机断点 — 顶栏会折行");
  const mq = SRC.slice(SRC.search(/@media\s*\(max-width:\s*\d+px\)/));
  assert.ok(/topbar|header|h1/.test(mq.slice(0, 400)),
    "手机断点里没有处理顶栏");
});
