#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 MCP 数据到本地快照。

  python engine/sync.py --token xxx        # 拉菜单 + 套餐详情
  python engine/sync.py                    # 用现有缓存补齐缺失详情
  python engine/sync.py --force            # 全部重拉

产物：
  engine/data/menu.json            菜单（storeCode + items）
  engine/data/nutrition.json       营养表（160 行）
  engine/data/details/<code>.json  套餐详情（仅含套餐类 SKU）

只读：不调用任何写操作工具。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DETAILS = os.path.join(DATA, "details")
BASE = os.environ.get("MCD_MCP_BASE", "https://mcp.mcd.cn")
COMBO_KW = ("套餐", "三件套", "四件套", "分享餐", "随心选", "单人餐", "组合")


class Mcp:
    def __init__(self, token):
        self.token = token
        self.session = None
        self.protocol = None
        self.n = 0

    def _headers(self):
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream",
             "Authorization": "Bearer " + self.token}
        if self.session:
            h["Mcp-Session-Id"] = self.session
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _post(self, payload, timeout=40):
        req = urllib.request.Request(BASE,
                                     data=json.dumps(payload, ensure_ascii=False).encode(),
                                     headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sid = r.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            return r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")

    @staticmethod
    def _pick(ctype, body):
        if "text/event-stream" in ctype:
            last = None
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        last = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        pass
            return last
        return json.loads(body)

    def rpc(self, method, params=None, notify=False):
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            payload["id"] = self.n
        ctype, body = self._post(payload)
        if notify:
            return None
        msg = self._pick(ctype, body)
        if "error" in msg:
            raise RuntimeError(json.dumps(msg["error"], ensure_ascii=False))
        return msg.get("result", msg)

    def init(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "mcd-engine", "version": "0.1"}})
        self.protocol = r.get("protocolVersion")
        self.rpc("notifications/initialized", {}, notify=True)

    def call(self, name, args):
        res = self.rpc("tools/call", {"name": name, "arguments": args})
        text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        i = text.find("## Original Response")
        if i != -1:
            blob = text[i:].split("\n", 1)[1].lstrip()
        else:
            # 部分工具（如 delivery-query-addresses）在 JSON 前夹了说明表格
            j = text.find('{"success"')
            blob = text[j:] if j != -1 else text.lstrip()
        return json.JSONDecoder().raw_decode(blob)[0]


def combo_like(name):
    return any(k in name for k in COMBO_KW)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""))
    ap.add_argument("--store-code", default="")
    ap.add_argument("--order-type", type=int, default=1)
    ap.add_argument("--be-type", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.makedirs(DETAILS, exist_ok=True)
    menu_path = os.path.join(DATA, "menu.json")

    if not args.token:
        if os.path.exists(menu_path):
            print("无 Token，使用现有快照。")
            return 0
        print("缺少 Token 且无快照。", file=sys.stderr)
        return 2

    mcp = Mcp(args.token)
    mcp.init()
    print("已握手：", mcp.protocol)

    # 1) 菜单
    if args.force or not os.path.exists(menu_path):
        store = args.store_code
        if not store:
            try:
                orders = mcp.call("order-list", {})
                store = str((orders.get("data") or {}).get("list", [{}])[0].get("storeCode", ""))
                store_name = (orders.get("data") or {}).get("list", [{}])[0].get("storeName", "")
            except Exception:
                store, store_name = "", ""
        else:
            store_name = ""
        if not store:
            print("拿不到门店编码，请用 --store-code 指定。", file=sys.stderr)
            return 3
        meals = mcp.call("query-meals", {"storeCode": store,
                                         "orderType": args.order_type, "beType": args.be_type})
        items = (meals.get("data") or {}).get("meals") or {}
        snapshot = {"storeCode": store, "storeName": store_name,
                    "orderType": args.order_type, "beType": args.be_type,
                    "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(items), "items": items}
        json.dump(snapshot, open(menu_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"菜单已保存：{len(items)} 个 SKU → {menu_path}")
    else:
        snapshot = json.load(open(menu_path, encoding="utf-8"))
        print(f"菜单已存在：{snapshot.get('count')} 个 SKU（--force 可重拉）")

    store = snapshot["storeCode"]

    # 2) 营养表
    nut_path = os.path.join(DATA, "nutrition.json")
    if args.force or not os.path.exists(nut_path):
        res = mcp.call("list-nutrition-foods", {})
        raw = res.get("data")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        m = re.match(r"\[(\d+)\]\{(.+?)\}:", lines[0])
        cols = [c.strip() for c in m.group(2).split(",")]
        import csv
        import io
        rows = list(csv.DictReader(io.StringIO("\n".join([",".join(cols)] + lines[1:]))))
        out = []
        for r in rows:
            out.append({
                "name": r["productName"],
                "kj": r["energyKj"], "kcal": r["energyKcal"], "protein": r["protein"],
                "fat": r["fat"], "carb": r["carbohydrate"],
                "sodium": r["sodium"], "calcium": r["calcium"],
            })
        json.dump({"fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": out},
                  open(nut_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"营养表已保存：{len(out)} 行 → {nut_path}")

    # 3) 套餐详情
    targets = [(c, v["name"]) for c, v in snapshot["items"].items() if combo_like(v.get("name", ""))]
    print(f"套餐类 SKU：{len(targets)} 个")
    ok = skip = fail = 0
    for code, name in targets:
        p = os.path.join(DETAILS, f"{code}.json")
        if os.path.exists(p) and not args.force:
            skip += 1
            continue
        try:
            d = mcp.call("query-meal-detail", {"storeCode": store, "orderType": args.order_type,
                                               "beType": args.be_type, "code": code})
            data = d.get("data")
            if not data:
                print(f"  空详情：{code} {name}")
                fail += 1
                continue
            json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            ok += 1
            print(f"  ✓ {code} {name}｜轮次 {len(data.get('rounds', []))}")
            time.sleep(0.15)
        except Exception as e:
            fail += 1
            print(f"  ✗ {code} {name}｜{e}")

    print(f"\n详情：新增 {ok}｜已有 {skip}｜失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
