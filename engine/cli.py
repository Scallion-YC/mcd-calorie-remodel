#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行入口。

  python engine/cli.py coverage
  python engine/cli.py list
  python engine/cli.py plan --mode cut --kcal 600 --weight 70
  python engine/cli.py plan --mode bulk --kcal 900 --weight 70 --show 3
  python engine/cli.py selftest

不联网。数据来自 engine/data/ 快照（由 sync.py 生成）。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402


def load_all():
    rows, ts = core.load_nutrition()
    book = core.Book(rows, core.load_aliases(), core.load_derived())
    menu = core.load_menu()
    details = core.load_details()
    zero = core.load_zero_whitelist()
    return book, menu, details, zero, ts


def cmd_coverage(args):
    book, menu, details, zero, ts = load_all()
    print(f"营养表 {len(book.rows)} 行（快照 {ts}）｜重名 {len(book.dups)} 处 {book.dups}")
    print(f"菜单 {menu.get('count')} 个 SKU｜门店 {menu.get('storeCode')} {menu.get('storeName','')}")
    print(f"套餐详情 {len(details)} 份")

    pool = core.candidates(menu, details, book, zero)
    total_comp = sum(c.total_comp for c in pool)
    hit_comp = sum(c.hit_comp for c in pool)
    alias_comp = sum(c.alias_comp for c in pool)
    derived_comp = sum(c.derived_comp for c in pool)
    print(f"\n可完整计算（exact）的套餐：{len(pool)} 个")
    print(f"组件级命中：{hit_comp}/{total_comp} = {hit_comp/total_comp:.0%}"
          f"（别名 {alias_comp} 项，倍数推导 {derived_comp} 项）" if total_comp else "组件级命中：0")

    partial = []
    for code, d in details.items():
        item = (menu.get("items") or {}).get(code)
        if not item:
            continue
        c = core.Combo(code, item, d, book, zero)
        if c.status != "exact":
            partial.append(c)
    if partial:
        print(f"\npartial {len(partial)} 个，缺失项前三：")
        for c in partial[:3]:
            print(f"  · {c.name}：缺 {c.missing}")
    return 0


def cmd_list(args):
    book, menu, details, zero, _ = load_all()
    pool = core.candidates(menu, details, book, zero)
    pool.sort(key=lambda c: -c.density)
    print(f"{'code':12} {'名称':24} {'kcal':>6} {'蛋白':>5} {'价格':>6} {'密度':>6} {'蛋白/元':>7}")
    print("-" * 74)
    for c in pool:
        print(f"{c.code:12} {c.name[:22]:24} {c.kcal:6.0f} {c.protein:5.0f} "
              f"{(c.base_price or 0):6.1f} {c.density:6.2f} {c.protein_per_yuan:7.2f}")
    print(f"\n共 {len(pool)} 个可完整计算")
    return 0


def cmd_plan(args):
    book, menu, details, zero, _ = load_all()
    floor = core.protein_floor_for(args.mode, args.weight, args.meals)
    top, pool, state = core.solve(args.mode, args.kcal, floor, menu, details, book, zero, top=max(args.show, 1))
    if not top:
        print("候选池为空：请先运行 engine/sync.py 拉取套餐详情。")
        return 1

    taste = core.load_taste()
    factors = core.load_factors()
    for i, c in enumerate(top, 1):
        if i > 1:
            print("\n" + "=" * 46 + "\n")
        sugg = core.suggestions(c, book, zero, args.mode, args.kcal, taste)
        notes = core.modification_notes(c, factors)
        print(core.render(c, sugg, notes, args.mode, args.kcal, floor, state))
    return 0


def cmd_estimate(args):
    book, menu, details, zero, _ = load_all()
    table = core.load_estimates()
    names = [args.name] if args.name else list(table.keys())
    if not table:
        print("estimates.json 为空。")
        return 0
    for n in names:
        r = core.estimate(n, book, table)
        if not r:
            print(f"{n}：没有匹配的锚点商品，无法估算。")
            continue
        print(f"【估算】{r['name']}")
        print("营养表无此条，按同类商品推算，仅供点单参考，不进入推荐排序。")
        print(f"热量 {r['kcal_lo']}–{r['kcal_hi']} kcal（中值 {r['kcal_mid']}）"
              f"· 蛋白 {r['protein_lo']}–{r['protein_hi']} g")
        print(f"依据：参照 {r['anchor']}，{r['why']}")
        print(f"误差带：±{r['band']*100:.0f}%")
        print()
    return 0


def cmd_selftest(args):
    book, menu, details, zero, _ = load_all()
    pool = core.candidates(menu, details, book, zero)
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ✓ {name}")
        else:
            fail += 1
            print(f"  ✗ {name}  {detail}")

    print("验收 1：套餐热量 = 组件营养求和")
    sample = pool[:5]
    for c in sample:
        re_sum = 0.0
        for comp in c.comps:
            m = book.macro(comp["name"], zero)
            if m:
                re_sum += m[0] * comp["qty"]
        check(f"{c.name[:18]} {c.kcal:.0f} kcal", abs(re_sum - c.kcal) < 0.01,
              f"重算 {re_sum}")

    print("\n验收 2：改造差值 = 两行营养相减")
    if sample:
        c = sample[0]
        sugg = core.suggestions(c, book, zero, "cut", 2000, core.load_taste(), limit=1)
        if sugg:
            s = sugg[0]
            a = book.macro(s["from"], zero)
            b = book.macro(s["to"], zero)
            check(f"{s['from']}→{s['to']} {s['d_kcal']:+.0f} kcal",
                  abs((b[0] - a[0]) - s["d_kcal"]) < 0.01)
        else:
            check("有可推荐的改动", False, "该套餐在同轮次内没有更优替换")

    print("\n验收 3：覆盖率可复现")
    hit = sum(c.hit_comp for c in pool)
    tot = sum(c.total_comp for c in pool)
    check(f"组件命中 {hit}/{tot}", hit <= tot and tot > 0)

    print("\n验收 4：partial 不冒充完整")
    fake_detail = {"rounds": [{"name": "主食", "choices": [
        {"code": "1", "name": "麦辣鸡腿堡", "quantity": 1, "isDefault": 1},
        {"code": "2", "name": "不存在的餐品XYZ", "quantity": 1, "isDefault": 1}]}]}
    fc = core.Combo("fake", {"name": "测试套餐", "currentPrice": "30"}, fake_detail, book, zero)
    check(f"状态={fc.status}，缺失={len(fc.missing)}", fc.status == "partial" and fc.missing)

    print("\n验收 5：三种模式排序不同")
    orders = {}
    for m in ("cut", "bulk", "keep"):
        t, _, _st = core.solve(m, 1200, core.protein_floor_for(m, 70), menu, details, book, zero, top=3)
        orders[m] = [c.code for c in t]
    check("cut/bulk/keep 排序非全等", len({tuple(v) for v in orders.values()}) > 1, str(orders))

    print("\n验收 6：零卡白名单生效")
    m1 = book.macro("无糖可口可乐中杯", zero)
    m2 = book.macro("无糖可口可乐中杯", set())
    check("白名单内保留 0 卡，名单外视为 unknown", m1 is not None and m2 is None,
          f"{m1} / {m2}")

    print("\n验收 7：估算区间合理且锚点存在")
    est = core.load_estimates()
    if est:
        bad = []
        for nm in est:
            r = core.estimate(nm, book, est)
            if not r or not (r["kcal_lo"] < r["kcal_mid"] < r["kcal_hi"]):
                bad.append(nm)
        check(f"{len(est)} 个估算项区间有序", not bad, str(bad))
        check("估算不进入推荐池",
              not any("龙焰" in c.name for c in pool))
    else:
        check("estimates.json 非空", False)

    print("\n验收 8：因子表键名与区间估算")
    fac = core.load_factors()
    real = set()
    for d in details.values():
        for rd in d.get("rounds", []) or []:
            for ch in rd.get("choices", []) or []:
                for it in (ch.get("modification") or {}).get("items", []) or []:
                    for v in it.get("values", []) or []:
                        real.add(v.get("name", ""))
    dead = [k for k in fac if not k.startswith("_") and k not in real]
    check("因子表没有真实数据里不存在的键", not dead, str(dead))

    host = next((c for c in pool
                 if any(n["name"] == "麦香鸡酱" for n in core.modification_notes(c, fac))), None)
    if host:
        tmp = dict(fac)
        tmp["麦香鸡酱"] = {"kcal": None, "estimate": {"lo": 60, "hi": 75},
                       "unit": "份", "confidence": "low"}
        rng = [n for n in core.modification_notes(host, tmp) if n["name"] == "麦香鸡酱"]
        check("无定值时改走区间（k_lo / k_hi）",
              bool(rng) and rng[0].get("k_lo") == -75 and rng[0].get("k_hi") == -60,
              str(rng[:1]))
    else:
        check("找到含麦香鸡酱的套餐", False)

    print(f"\n{ok} 通过 / {fail} 失败")
    return 0 if fail == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("coverage", help="覆盖率与数据规模")
    sub.add_parser("list", help="列出可完整计算的套餐")
    sub.add_parser("selftest", help="离线自测")

    e = sub.add_parser("estimate", help="当季新品的区间估算")
    e.add_argument("--name", default="", help="商品名，省略则列出全部")

    p = sub.add_parser("plan", help="出方案")
    p.add_argument("--mode", default="cut", choices=list(core.MODES))
    p.add_argument("--kcal", type=float, default=600)
    p.add_argument("--weight", type=float, default=0)
    p.add_argument("--meals", type=int, default=3)
    p.add_argument("--show", type=int, default=1)

    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return {"coverage": cmd_coverage, "list": cmd_list, "estimate": cmd_estimate,
            "plan": cmd_plan, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
