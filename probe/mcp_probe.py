#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳 MCP 实测探针 —— 一次回答 `产品需求手册.md` §17 的四个阻塞项

  用法：
    set MCD_MCP_TOKEN=你的Token          (PowerShell: $env:MCD_MCP_TOKEN="...")
    python mcp_probe.py tools             # ① 握手 + 全量工具与参数（顺带验证 token）
    python mcp_probe.py nutrition         # ② 营养表体检：行数/列/重复/口径
    python mcp_probe.py chain             # ③ 订单→门店→菜单→套餐详情，看能否展开到组件
    python mcp_probe.py call query-meals --args "{\"storeCode\":\"1450384\"}"

  设计约束：
    - 零第三方依赖，Python 3.9+
    - 只调用只读工具，永不触碰 create-order / cancel-order / draw-lottery 等写操作
    - 原始返回全部落盘到 out/raw/，报告写 out/report.md，便于复核
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = os.environ.get("MCD_MCP_BASE", "https://mcp.mcd.cn")
TOKEN = os.environ.get("MCD_MCP_TOKEN", "").strip()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
RAW = os.path.join(OUT, "raw")

READ_ONLY_HINT = ("list", "query", "calculate", "now", "order-list", "available", "campaign")
FORBIDDEN = {"create-order", "cancel-order", "draw-lottery", "mall-create-order",
             "auto-bind-coupons", "party-order-create", "delivery-create-address"}


# ---------------------------------------------------------------- transport

class Mcp:
    """最小 Streamable HTTP 客户端。返回体可能是 JSON，也可能是 SSE。"""

    def __init__(self, base, token):
        self.base = base.rstrip("/")
        self.token = token
        self.session = None
        self.protocol = None
        self._id = 0

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token,
            "User-Agent": "mcd-probe/0.1",
        }
        if self.session:
            h["Mcp-Session-Id"] = self.session
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _post(self, payload, timeout=30):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                sid = r.headers.get("Mcp-Session-Id")
                if sid:
                    self.session = sid
                return r.status, r.headers.get("Content-Type", ""), body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            return e.code, e.headers.get("Content-Type", ""), body

    @staticmethod
    def _parse_body(ctype, body):
        """SSE 取最后一条 data；否则按 JSON 解析。"""
        if "text/event-stream" in ctype or body.lstrip().startswith(("event:", "data:", "id:")):
            msgs = []
            for line in body.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk and chunk != "[DONE]":
                        try:
                            msgs.append(json.loads(chunk))
                        except json.JSONDecodeError:
                            pass
            return msgs[-1] if msgs else None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def rpc(self, method, params=None, notify=False):
        if notify:
            self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})
            return None
        self._id += 1
        status, ctype, body = self._post(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        )
        msg = self._parse_body(ctype, body)
        if msg is None:
            raise RuntimeError(f"HTTP {status} 返回无法解析：{body[:300]}")
        if "error" in msg:
            raise RuntimeError(f"JSON-RPC 错误：{json.dumps(msg['error'], ensure_ascii=False)}")
        return msg.get("result", msg)

    def handshake(self):
        res = self.rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mcd-probe", "version": "0.1"},
        })
        self.protocol = res.get("protocolVersion") or "2025-06-18"
        self.rpc("notifications/initialized", {}, notify=True)
        return res

    def tools(self):
        out, cursor = [], None
        while True:
            res = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            out += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                return out

    def call(self, name, args=None):
        if name in FORBIDDEN:
            raise SystemExit(f"拒绝调用写操作工具：{name}")
        return self.rpc("tools/call", {"name": name, "arguments": args or {}})


# ---------------------------------------------------------------- parsing

def text_of(result):
    """把 tools/call 的 content 数组拼成纯文本。"""
    if not isinstance(result, dict):
        return str(result)
    parts = []
    for c in result.get("content", []) or []:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts)


def json_of(text):
    """真 JSON 藏在 `## Original Response` 之后。用 raw_decode 吃掉尾部的说明文字。"""
    m = re.search(r"##\s*Original Response\s*\n(.*)$", text, re.S)
    blob = (m.group(1) if m else text).lstrip()
    try:
        return json.JSONDecoder().raw_decode(blob)[0]
    except json.JSONDecodeError:
        return None


def toon_of(payload):
    """营养表是 TOON：`[160]{a,b,c}:` + 两空格缩进的逗号行。返回 (cols, rows)。"""
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    if not isinstance(payload, str):
        return None, []
    lines = [l.strip() for l in payload.splitlines() if l.strip()]
    if not lines:
        return None, []
    m = re.match(r"\[(\d+)\]\{(.+?)\}:", lines[0])
    if not m:
        return None, []
    cols = [c.strip() for c in m.group(2).split(",")]
    rows = list(csv.DictReader(io.StringIO("\n".join([",".join(cols)] + lines[1:]))))
    return cols, rows


def load_raw(name):
    """读回已落盘的 tools/call 结果。"""
    p = os.path.join(RAW, name + ".json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return json_of(text_of(d))


def table_of(text):
    """营养表可能是逗号分隔文本表格。返回 (header, rows)。"""
    m = re.search(r"##\s*Original Response\s*\n(.*)$", text, re.S)
    blob = m.group(1).strip() if m else text
    lines = [l for l in blob.splitlines() if l.strip()]
    if len(lines) < 2:
        return None, []
    head = lines[0]
    if "," not in head:
        return None, []
    rd = csv.DictReader(io.StringIO("\n".join(lines)))
    return rd.fieldnames, list(rd)


def deep_find(obj, keys, limit=8):
    """递归找指定 key，返回 [(path, value)]。"""
    hits = []

    def walk(o, path=""):
        if len(hits) >= limit:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}" if path else k
                if k in keys and not isinstance(v, (dict, list)):
                    hits.append((p, v))
                walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o[:20]):
                walk(v, f"{path}[{i}]")

    walk(obj)
    return hits


def dump(name, obj):
    os.makedirs(RAW, exist_ok=True)
    p = os.path.join(RAW, name + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return p


# ---------------------------------------------------------------- commands

def cmd_tools(mcp, args):
    info = mcp.handshake()
    tools = mcp.tools()
    dump("tools_list", {"server": info, "tools": tools})

    print(f"服务端：{info.get('serverInfo', {}).get('name')} "
          f"{info.get('serverInfo', {}).get('version')}｜协议 {mcp.protocol}")
    print(f"会话：{mcp.session or '（服务端未下发 Mcp-Session-Id）'}")
    print(f"工具数：{len(tools)}\n")
    print(f"{'名称':30} {'必填参数':38} 说明")
    print("-" * 110)
    for t in tools:
        sch = t.get("inputSchema") or {}
        req = sch.get("required") or []
        props = list((sch.get("properties") or {}).keys())
        sig = ",".join(req) if req else ("(" + ",".join(props[:3]) + ")")
        desc = (t.get("description") or "").replace("\n", " ")[:46]
        print(f"{t.get('name',''):30} {sig[:38]:38} {desc}")
    print(f"\n已保存：{os.path.join(RAW, 'tools_list.json')}")
    return 0


def cmd_nutrition(mcp, args):
    mcp.handshake()
    res = mcp.call("list-nutrition-foods", {})
    text = text_of(res)
    dump("list-nutrition-foods", res)

    data = json_of(text)
    header, rows = (None, [])
    if isinstance(data, dict) or isinstance(data, str):
        header, rows = toon_of(data)

    print(f"返回文本 {len(text)} 字符｜解析方式："
          f"{'TOON 表格' if header else '未识别'}")
    if not header:
        print("\n未解析出表格，原始文本前 600 字：\n" + text[:600])
        return 1

    print(f"列（{len(header)}）：{', '.join(header)}")
    print(f"行数：{len(rows)}")

    name_key = next((h for h in header if re.search(r"名称|name", h, re.I)), header[0])
    names = [str(r.get(name_key, "")).strip() for r in rows]
    cnt = {}
    for n in names:
        cnt[n] = cnt.get(n, 0) + 1
    dups = {k: v for k, v in cnt.items() if v > 1 and k}
    print(f"重名条目：{len(dups)} 个")
    for k, v in list(dups.items())[:10]:
        print(f"  · {k} × {v}")

    kcol = next((h for h in header if "kcal" in h.lower()), None)
    if kcol:
        vals = []
        for r in rows:
            v = str(r.get(kcol, "")).strip()
            if re.fullmatch(r"-?\d+(\.\d+)?", v):
                vals.append(float(v))
        zeros = sum(1 for v in vals if v == 0)
        if vals:
            print(f"{kcol} 范围 {min(vals):.0f}–{max(vals):.0f}｜均值 {sum(vals)/len(vals):.0f}｜"
                  f"数值为 0 的行 {zeros}（0 不等于缺失，下游要区分）")

    pcol = next((h for h in header if "protein" in h.lower() or "蛋白" in h), None)
    if pcol:
        top = sorted(rows, key=lambda r: -float(r.get(pcol) or 0))[:3]
        print("蛋白最高的 3 行：")
        for r in top:
            print(f"  · {r.get(name_key)}：蛋白 {r.get(pcol)}｜{r.get(kcol)} kcal")

    print("\n前三行样例：")
    for r in rows[:3]:
        print("  " + json.dumps(r, ensure_ascii=False)[:200])

    with open(os.path.join(OUT, "nutrition.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    print(f"\n已保存：{os.path.join(OUT, 'nutrition.csv')}")
    return 0


def cmd_coverage(mcp, args):
    """菜单 SKU 与营养表按名称对齐的覆盖率。"""
    nut = load_raw("list-nutrition-foods")
    meal = load_raw("query-meals")
    if mcp and not nut:
        mcp.handshake()
        nut = json_of(text_of(mcp.call("list-nutrition-foods", {})))
        dump("list-nutrition-foods", json.load(open(os.path.join(RAW, "list-nutrition-foods.json"), encoding="utf-8")) if os.path.exists(os.path.join(RAW, "list-nutrition-foods.json")) else {})
    if mcp and not meal:
        print("缺少菜单数据，请先跑 chain。")
        return 1
    cols, rows = toon_of(nut)
    meals = ((meal or {}).get("data") or {}).get("meals") or {}
    if not cols or not meals:
        print("数据不全：需要 list-nutrition-foods 与 query-meals 的原始返回。")
        return 1

    def norm(s):
        s = unicodedata.normalize("NFKC", str(s))
        return re.sub(r"[\s\u3000]", "", s)

    nmap = {norm(r["productName"]): r for r in rows}
    combo_kw = ("套餐", "三件套", "四件套", "分享餐", "随心选", "双人", "多人", "拼盘")
    hit, combo, miss = [], [], []
    for code, v in meals.items():
        n = norm(v.get("name", ""))
        if n in nmap:
            hit.append((code, v["name"]))
        elif any(k in n for k in combo_kw):
            combo.append((code, v["name"]))
        else:
            miss.append((code, v["name"]))

    total = len(meals)
    print(f"营养表 {len(rows)} 行｜菜单 SKU {total} 个")
    print(f"  直接命中     {len(hit):4}  {len(hit)/total:5.0%}")
    print(f"  套餐需拆组件 {len(combo):4}  {len(combo)/total:5.0%}")
    print(f"  单品无营养行 {len(miss):4}  {len(miss)/total:5.0%}")
    print(f"\n菜单级覆盖率 {len(hit)/total:.0%}；营养表内「套餐」类行数 "
          f"{sum(1 for r in rows if '套餐' in r['productName'])}")
    print("\n缺失单品（前 20）：")
    for _, n in miss[:20]:
        print("  -", n)

    with open(os.path.join(OUT, "coverage.json"), "w", encoding="utf-8") as f:
        json.dump({"hit": hit, "combo": combo, "miss": miss}, f, ensure_ascii=False, indent=2)
    print(f"\n明细已保存：{os.path.join(OUT, 'coverage.json')}")
    return 0


def cmd_chain(mcp, args):
    mcp.handshake()
    report = []

    def step(title, fn):
        print(f"\n=== {title} ===")
        try:
            r = fn()
            return r
        except Exception as e:
            print(f"失败：{e}")
            report.append((title, f"失败：{e}"))
            return None

    # 1) 历史订单 → storeCode
    orders = step("order-list", lambda: mcp.call("order-list", {}))
    store_code = args.store_code
    if orders:
        txt = text_of(orders)
        dump("order-list", orders)
        data = json_of(txt)
        hits = deep_find(data, {"storeCode", "storeId", "storecode"}, 4) if data else []
        if hits and not store_code:
            store_code = str(hits[0][1])
            print(f"从订单取到 storeCode = {store_code}（{hits[0][0]}）")
        elif not hits:
            print("订单里没找到 storeCode，原始文本前 300 字：\n" + txt[:300])
    if not store_code:
        print("\n没有 storeCode，跳过后续。请用 --store-code 指定，或先调 query-nearby-stores。")
        return 1

    # 2) 菜单
    base = {"storeCode": store_code, "orderType": args.order_type, "beType": args.be_type}
    meals = step(f"query-meals {base}", lambda: mcp.call("query-meals", base))
    if not meals:
        return 1
    dump("query-meals", meals)
    meal_text = text_of(meals)
    meal_json = json_of(meal_text)
    print(f"菜单文本 {len(meal_text)} 字符，解析为 {'JSON' if meal_json else '纯文本'}")

    # 3) 找一个套餐类商品的编码
    code = args.meal_code
    if not code and meal_json:
        hits = deep_find(meal_json, {"code", "mealCode", "productCode", "spuId"}, 60)
        for path, val in hits:
            if re.search(r"套餐|组合|三件套", path):
                code = str(val)
                break
        if not code and hits:
            code = str(hits[0][1])
        print(f"选用商品编码 = {code}")

    if not code:
        print("未能自动定位商品编码，请用 --meal-code 指定。")
        return 1

    # 4) 套餐详情 —— 这里看能否展开到组件与特制项
    dargs = dict(base, code=code)
    detail = step(f"query-meal-detail code={code}",
                  lambda: mcp.call("query-meal-detail", dargs))
    if not detail:
        return 1
    p = dump("query-meal-detail", detail)
    dtext = text_of(detail)
    djson = json_of(dtext)
    print(f"详情文本 {len(dtext)} 字符，解析为 {'JSON' if djson else '纯文本'}｜已存 {p}")

    if djson:
        keys = set()
        def collect(o):
            if isinstance(o, dict):
                keys.update(o.keys())
                for v in o.values():
                    collect(v)
            elif isinstance(o, list):
                for v in o[:20]:
                    collect(v)
        collect(djson)
        hit = sorted(k for k in keys if re.search(r"特制|替换|可选|option|replace|custom|attr", k, re.I))
        print(f"\n字段总数 {len(keys)}｜特制/替换相关字段：{hit if hit else '无'}")
    else:
        print("\n非 JSON，前 600 字：\n" + dtext[:600])

    print("\n判定要点：")
    print("  1. 详情里有没有『可替换项 / 特制选项』→ 决定改造清单能否落到具体项")
    print("  2. 有无 component 级营养 → 决定去酱能否精确算")
    print("  3. 若只有价格没有营养 → 改造层必须自建因子表并标『估算』")
    return 0


def cmd_call(mcp, args):
    mcp.handshake()
    payload = json.loads(args.args) if args.args else {}
    res = mcp.call(args.tool, payload)
    p = dump(args.tool.replace("/", "_"), res)
    text = text_of(res)
    print(text[:3000])
    print(f"\n---\n原文 {len(text)} 字符，已存 {p}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="麦当劳 MCP 实测探针")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tools", help="握手并列出全部工具与参数")
    sub.add_parser("nutrition", help="营养表体检")
    sub.add_parser("coverage", help="菜单与营养表对齐覆盖率（需先跑 chain）")
    c = sub.add_parser("chain", help="订单→门店→菜单→详情")
    c.add_argument("--store-code", default="")
    c.add_argument("--meal-code", default="")
    c.add_argument("--order-type", type=int, default=1, choices=[1, 2])
    c.add_argument("--be-type", type=int, default=1, choices=[1, 2, 5, 6])
    d = sub.add_parser("call", help="调用单个工具")
    d.add_argument("tool")
    d.add_argument("--args", default="")

    args = ap.parse_args()

    if not TOKEN:
        print("缺少 MCD_MCP_TOKEN。\n"
              "  1. 打开 https://open.mcd.cn/mcp 手机号登录\n"
              "  2. 右上角『控制台』→ 激活 → 复制 Token\n"
              "  3. PowerShell: $env:MCD_MCP_TOKEN=\"你的Token\"\n"
              "  注：不带 Token 时网关返回 403『系统错误』，不是 401，别被误导。", file=sys.stderr)
        return 2

    os.makedirs(OUT, exist_ok=True)
    mcp = Mcp(BASE, TOKEN)
    try:
        return {"tools": cmd_tools, "nutrition": cmd_nutrition, "coverage": cmd_coverage,
                "chain": cmd_chain, "call": cmd_call}[args.cmd](mcp, args)
    except urllib.error.URLError as e:
        print(f"网络错误：{e}", file=sys.stderr)
        return 3
    except RuntimeError as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            print(f"Token 无效或已过期：{msg}", file=sys.stderr)
            return 4
        print(msg, file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
