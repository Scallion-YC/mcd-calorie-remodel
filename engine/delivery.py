#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外送场景：同一套营养算法，另加配送与包装费。

  set MCD_MCP_TOKEN=你的Token
  python engine/delivery.py --mode cut --kcal 900 --weight 70 --limit 5
  python engine/delivery.py --address-id <id> --store-index 1

结论先说：外送不改变热量与营养，差异只在配送费、包装费和到手价。
脚本只做两件事——按到店同一套规则选餐，再用官方核价把到手价算出来。

不显示地址、联系人、电话；不创建地址；不下单。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
from sync import Mcp  # noqa: E402

COMBO_KW = ("套餐", "三件套", "四件套", "分享餐", "随心选", "单人餐", "组合")


def pick_address(mcp, want=None):
    d = mcp.call("delivery-query-addresses", {}).get("data") or {}
    addrs = d.get("addresses") or []
    if not addrs:
        return None, 0
    if want:
        for a in addrs:
            if a.get("addressId") == want:
                return a, len(addrs)
        return None, len(addrs)
    return addrs[0], len(addrs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""))
    ap.add_argument("--address-id", default="")
    ap.add_argument("--store-index", type=int, default=0, help="多门店时选第几家，从 0 开始")
    ap.add_argument("--mode", default="cut", choices=list(core.MODES))
    ap.add_argument("--kcal", type=float, default=900)
    ap.add_argument("--weight", type=float, default=70)
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    if not args.token:
        print("缺少 MCD_MCP_TOKEN", file=sys.stderr)
        return 2

    mcp = Mcp(args.token)
    mcp.init()

    addr, total = pick_address(mcp, args.address_id or None)
    if not addr:
        print(f"没有可用的外送地址（共 {total} 个）。"
              "本工具不会创建地址：请先在麦当劳 App 里保存一个收货地址。", file=sys.stderr)
        return 3

    stores = mcp.call("delivery-query-stores", {"beType": 2, "addressId": addr["addressId"]}).get("data") or []
    if not stores:
        print("该地址附近没有可外送门店。", file=sys.stderr)
        return 4
    if args.store_index >= len(stores):
        args.store_index = 0
    store = stores[args.store_index]

    print(f"外送门店：{store['storeName']}（{store['storeCode']}）")
    print(f"地址：已保存地址 #{args.store_index + 1} / 共 {total} 个（内容隐去）")

    base = {"storeCode": store["storeCode"], "orderType": 2, "beType": 2, "beCode": store["beCode"]}
    meals = (mcp.call("query-meals", dict(base)).get("data") or {}).get("meals") or {}
    if not meals:
        print("这家店当前无可售商品（可能未营业）。换一家试试：--store-index 1", file=sys.stderr)
        return 5

    combo_codes = [c for c, v in meals.items() if any(k in v.get("name", "") for k in COMBO_KW)]
    details = {}
    for code in combo_codes:
        try:
            d = mcp.call("query-meal-detail", dict(base, code=code))
            if d.get("data"):
                details[code] = d["data"]
        except Exception:
            continue

    rows, _ = core.load_nutrition()
    book = core.Book(rows, core.load_aliases(), core.load_derived())
    zero = core.load_zero_whitelist()
    menu = {"items": meals, "count": len(meals)}
    pool = core.candidates(menu, details, book, zero)
    if not pool:
        print("外卖菜单里没有可完整计算的套餐。", file=sys.stderr)
        return 6

    # 覆盖率：外卖菜单与营养表的对齐情况，必须一并报出
    total_combo = sum(1 for v in meals.values()
                      if any(k in v.get("name", "") for k in COMBO_KW))
    miss = {}
    for code, d in details.items():
        c = core.Combo(code, meals[code], d, book, zero)
        for nm in c.missing:
            miss[nm] = miss.get(nm, 0) + 1
    top_miss = sorted(miss.items(), key=lambda kv: -kv[1])[:3]

    floor = core.protein_floor_for(args.mode, args.weight)
    plans, _, state = core.solve(args.mode, args.kcal, floor, menu, details, book, zero, top=args.limit)

    print(f"额度 {args.kcal:.0f} kcal · 蛋白目标 {floor:g} g · 模式 {core.MODES[args.mode]['label']}")
    if state == "protein_short":
        print(f"提示：该额度内没有套餐能达到蛋白 {floor:g} g，以下为最接近的方案。")
    print(f"数据：套餐类 {total_combo} 个，可完整计算 {len(pool)} 个"
          f"（{len(pool)/total_combo:.0%}）" if total_combo else "数据：无可比对套餐")
    if top_miss:
        print("      未覆盖的主要原因：" + "、".join(f"{n}（{k} 次）" for n, k in top_miss))
    print()
    print(f"{'套餐':26} {'热量':>5} {'蛋白':>4} {'商品':>6} {'配送':>5} {'包装':>5} {'到手':>6}")
    print("-" * 66)
    for c in plans:
        try:
            d = mcp.call("calculate-price", dict(base, items=[{"productCode": c.code, "quantity": 1}])).get("data") or {}
        except Exception:
            d = {}
        goods = (d.get("productPrice") or c.base_price * 100 or 0) / 100
        ship = (d.get("deliveryPrice") or 0) / 100
        pack = (d.get("packingPrice") or 0) / 100
        total_price = (d.get("price") or 0) / 100
        print(f"{c.name[:24]:26} {c.kcal:5.0f} {c.protein:4.0f} "
              f"{goods:6.1f} {ship:5.1f} {pack:5.1f} {total_price:6.1f}")

    print()
    print("说明：外送不改变热量与营养，口径与到店完全一致；差异在费用与渠道定价。")
    print("      外卖商品价可能高于到店（本例 双层吉士汉堡套餐 到店 39.5 / 外送 40.5），")
    print("      所以到手价必须用官方 calculate-price 算，不能拿到店价加运费去推。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
