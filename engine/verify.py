#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格口径核验：把菜单价与官方 calculate-price 逐个对一遍。

  set MCD_MCP_TOKEN=你的Token
  python engine/verify.py --limit 8

只读，不下单。用于回答「页面上的实付到底是不是官方价」。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
from sync import Mcp  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""))
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    if not args.token:
        print("缺少 MCD_MCP_TOKEN", file=sys.stderr)
        return 2

    rows, _ = core.load_nutrition()
    book = core.Book(rows, core.load_aliases(), core.load_derived())
    menu = core.load_menu()
    details = core.load_details()
    zero = core.load_zero_whitelist()
    pool = core.candidates(menu, details, book, zero)
    pool.sort(key=lambda c: c.kcal)
    sample = pool[:args.limit]

    mcp = Mcp(args.token)
    mcp.init()
    base = {"storeCode": menu["storeCode"], "orderType": menu.get("orderType", 1),
            "beType": menu.get("beType", 1)}

    print(f"{'套餐':24} {'菜单价':>7} {'官方核价':>9} {'差额':>7}")
    print("-" * 52)
    ok = diff = err = 0
    for c in sample:
        try:
            r = mcp.call("calculate-price", dict(base, items=[{"productCode": c.code, "quantity": 1}]))
            data = r.get("data") or {}
            cents = data.get("price")
            official = cents / 100 if isinstance(cents, (int, float)) else None
            if official is None:
                reason = r.get("message") or "响应无 price 字段"
                print(f"{c.name[:22]:24} {c.base_price:7.1f} {'—':>9} {reason[:18]:>7}")
                err += 1
                continue
            d = official - (c.base_price or 0)
            flag = "一致" if abs(d) < 0.01 else f"差 {d:+.1f}"
            print(f"{c.name[:22]:24} {c.base_price:7.1f} {official:9.1f} {flag:>7}")
            if abs(d) < 0.01:
                ok += 1
            else:
                diff += 1
        except Exception as e:
            print(f"{c.name[:22]:24} {c.base_price:7.1f} {'ERR':>9} {str(e)[:30]:>7}")
            err += 1

    print(f"\n一致 {ok}｜不一致 {diff}｜失败 {err}")
    if diff:
        print("存在差额：菜单价可能未含优惠或已过期，展示层应改用 calculate-price。")
    return 0 if diff == 0 and err == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
