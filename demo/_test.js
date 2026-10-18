// 用最小 DOM 桩跑一遍 demo 页的内嵌脚本，验证运行时结果。
// 用法：node demo/_test.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const payload = html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function el(id) {
  return {
    id, textContent: id === "payload" ? payload : "", innerHTML: "", value: "900",
    dataset: {}, setAttribute() {}, addEventListener() {}, querySelectorAll: () => [],
  };
}
const nodes = {};
const document = {
  getElementById(id) { nodes[id] = nodes[id] || el(id); return nodes[id]; },
  querySelectorAll() { return []; },
};
const sandbox = { document, window: {}, console, String, Number, Math, JSON, Object, Array, isNaN, parseFloat };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(script, sandbox);

const E = sandbox.window.__demo;
let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name + (extra ? "  " + extra : "")); }
}

check("候选池非空（" + E.pool.length + " 个）", E.pool.length >= 20);

const r1 = E.solve("cut", 900, 37.3);
check("cut/900 有结果", r1.plans.length > 0);
const p1 = r1.plans[0];
check("首选 " + p1.name + " · " + Math.round(p1.kcal) + " kcal", Math.round(p1.kcal) === 865, "期望 865");
check("降级态为 protein_short", r1.state === "protein_short", r1.state);

const s1 = E.suggestions(p1, "cut", 900);
check("改造建议 1 条", s1.length === 1, "实际 " + s1.length);
if (s1.length) {
  check("建议为 中薯条→小杯玉米杯", s1[0].from === "中薯条" && s1[0].to === "小杯玉米杯",
        s1[0].from + "→" + s1[0].to);
  check("差值为 -236 kcal", Math.round(s1[0].dk) === -236, String(s1[0].dk));
}

const r2 = E.solve("bulk", 1000, 42);
check("bulk/1000 首选 " + r2.plans[0].name, Math.round(r2.plans[0].kcal) === 997);

const r3 = E.solve("keep", 700, 0);
check("keep/700 落在 ±10%", Math.abs(r3.plans[0].kcal - 700) <= 70,
      String(Math.round(r3.plans[0].kcal)));

check("零卡白名单生效（无糖可乐）", !!E.macro("无糖可口可乐中杯"));
check("别名命中（原味双层深海鳕鱼堡）", !!E.macro("原味双层深海鳕鱼堡"));
check("页面已渲染卡片", nodes["card"] && nodes["card"].innerHTML.length > 200);
check("脚注含 31 个可计算", nodes["foot"] && nodes["foot"].innerHTML.indexOf(">31<") >= 0);

// 第二轮：带 URL 参数初始化（分享链接用）
const nodes2 = {};
const document2 = {
  getElementById(id) { nodes2[id] = nodes2[id] || el(id); return nodes2[id]; },
  querySelectorAll() { return []; },
};
const sandbox2 = {
  document: document2, window: {}, console, String, Number, Math, JSON, Object, Array,
  isNaN, parseFloat, decodeURIComponent, encodeURIComponent,
  location: { search: "?mode=bulk&kcal=1000&w=80" },
  history: { replaceState() {} },
};
sandbox2.globalThis = sandbox2;
vm.createContext(sandbox2);
vm.runInContext(script, sandbox2);
const E2 = sandbox2.window.__demo;

check("URL mode=bulk 生效", E2.state.mode === "bulk", E2.state.mode);
check("URL kcal=1000 生效", E2.state.cap === 1000, String(E2.state.cap));
check("URL w=80 生效", E2.state.weight === 80, String(E2.state.weight));

sandbox2.location.search = "?mode=keep&kcal=9999&w=1";
E2.applyParams();
check("越界参数被夹紧", E2.state.cap === 1400 && E2.state.weight === 35,
      E2.state.cap + "/" + E2.state.weight);

sandbox2.location.search = "?mode=xxx&kcal=abc";
E2.applyParams();
check("非法参数不覆盖原值", E2.state.mode === "keep" && E2.state.cap === 1400,
      E2.state.mode + "/" + E2.state.cap);

console.log("\n" + pass + " 通过 / " + fail + " 失败");
process.exit(fail ? 1 : 0);
