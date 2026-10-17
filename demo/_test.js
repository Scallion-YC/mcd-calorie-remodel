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

console.log("\n" + pass + " 通过 / " + fail + " 失败");
process.exit(fail ? 1 : 0);
