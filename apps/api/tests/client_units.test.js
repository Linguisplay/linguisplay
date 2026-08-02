// 🧪 客户端纯函数单测 (node --test, 零依赖零浏览器)。
// 从真实 HTML 里抽函数体来测 — 测的就是上线那份, 不是副本。
//     node --test tests/client_units.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "app", "static");
const read = (f) => fs.readFileSync(path.join(STATIC, f), "utf8");

/** 从页面源码里抠出一个具名函数并求值。按花括号配对取整个函数体 —
 *  别用「到行尾」抓 (函数换个行就断成半截, 报 SyntaxError, 看着像产品坏了)。*/
function grab(src, name) {
  const i = src.indexOf(`function ${name}(`);
  if (i < 0) throw new Error(`没找到 function ${name}`);
  let depth = 0, j = src.indexOf("{", i);
  const start = j;
  for (; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) break;
  }
  const body = src.slice(start, j + 1);
  // eslint-disable-next-line no-eval
  return eval(`(function ${name}${src.slice(i + `function ${name}`.length, start)}${body})`);
}

// ── 🔒 XSS: 转义器必须在【属性上下文】里也安全 ────────────────────────────
// 实弹 2026-08-02 审查: escapeHtml 只转 &<>, 而页面里大量 attr="${escapeHtml(x)}";
// 角色 avatar_url / 涌现角色名 / 地点名都是外部可控文本, 一个引号就能逃出属性写
// onerror=。转义器是全页的安全合约, 它必须一次管住所有 5 个 HTML 元字符。
const ATTACKS = [
  { name: "双引号逃逸", payload: 'x" onerror="alert(1)', mustNotContain: '"' },
  { name: "单引号逃逸", payload: "x' onerror='alert(1)", mustNotContain: "'" },
  { name: "标签注入", payload: '<img src=x onerror=alert(1)>', mustNotContain: "<" },
  { name: "闭标签", payload: "</script><script>alert(1)</script>", mustNotContain: "<" },
];

for (const [file, fn] of [["play.html", "escapeHtml"], ["studio.html", "esc"]]) {
  test(`${file} 的 ${fn}() 在属性上下文里安全`, () => {
    const f = grab(read(file), fn);
    for (const a of ATTACKS) {
      const out = f(a.payload);
      assert.ok(!out.includes(a.mustNotContain),
        `${a.name}: ${fn}(${JSON.stringify(a.payload)}) = ${JSON.stringify(out)} 仍含 ${a.mustNotContain}`);
    }
    // 转义后塞进属性, 解析出来必须还是原文 (不多不少)
    const out = f('a"b\'c<d>e&f');
    assert.equal(out.includes('"') || out.includes("'") || out.includes("<"), false);
    assert.ok(out.includes("&quot;") || out.includes("&#34;"), "双引号要被实体化");
  });
}

test("escapeHtml 不吃掉正常文本", () => {
  const f = grab(read("play.html"), "escapeHtml");
  assert.equal(f("蓝信一"), "蓝信一");
  assert.equal(f("Marek Duna"), "Marek Duna");
  assert.equal(f(""), "");
  assert.equal(f(null), "");
});

// ── 📖 分页: 中西分刀 (实弹 07-31: 英文从单词中间劈开) ───────────────────
test("paginate 西文按句成页且不劈单词", () => {
  const src = read("play.html");
  // 两个函数各自抽 (中间的注释行数会变 — 别把它们当一整块抓, 抓法太脆是测试的 bug)
  const one = (name) => {
    const i = src.indexOf(`function ${name}(`);
    assert.ok(i > 0, `没找到 function ${name}`);
    const end = src.indexOf("\n}", i);
    return src.slice(i, end + 2);
  };
  // eslint-disable-next-line no-eval
  eval(one("paginate") + "\n" + one("paginateLatin"));
  const en = paginate("First sentence here. Second one follows. Mr. Duna waits by the truck.");
  assert.equal(en.length, 3, "三句应成三页");
  assert.ok(en.some((p) => p.includes("Mr. Duna")), "Mr. 缩写不该被当句尾");
  for (const p of en) assert.ok(!/[a-z]$/.test(p) || p.includes(" "), `劈了单词: ${p}`);
  const zh = paginate("他站在门口很久没有说话。手里那把刀转得越来越慢了！");
  assert.equal(zh.length, 2, "中文分页回归");
});

// ── 📱 手机返回键 (实弹 08-01: backTo 传光杆名字 = 死键) ─────────────────
test("phoneShell 的 backTo 防呆: 光杆名字归一成 openPhone()", () => {
  const src = read("play.html");
  const i = src.indexOf("const go = !backTo");
  assert.ok(i > 0, "没抓到 backTo 防呆行");
  // 去掉 const: eval 里的 const 自成块作用域, 赋不到外层的 go (测试写法坑, 非产品问题)
  const line = src.slice(i, src.indexOf("\n", i)).replace(/^const /, "");
  const mk = (backTo) => { let go; eval(line); return go; };
  assert.equal(mk("phone"), "openPhone()", "光杆名字必须归一");
  assert.equal(mk("openInbox()"), "openInbox()", "正常调用原样保留");
  assert.equal(mk(""), "", "无返回键就是无");
});
