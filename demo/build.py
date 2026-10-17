#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 engine/data 的快照裁剪后内嵌进单文件 demo/index.html。

  python demo/build.py

产物：demo/index.html（零外部请求，可离线双击打开）
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "engine", "data")
DETAILS = os.path.join(DATA, "details")


def short_nutrition():
    d = json.load(open(os.path.join(DATA, "nutrition.json"), encoding="utf-8"))
    rows = []
    for r in d["rows"]:
        rows.append({
            "n": r["name"], "k": r["kcal"], "p": r["protein"], "f": r["fat"],
            "c": r["carb"], "na": r["sodium"], "ca": r["calcium"],
        })
    return {"fetchedAt": d.get("fetchedAt", ""), "rows": rows}


def short_menu():
    m = json.load(open(os.path.join(DATA, "menu.json"), encoding="utf-8"))
    items = {}
    for code, v in m["items"].items():
        items[code] = {"n": v.get("name", ""), "p": v.get("currentPrice", "")}
    return {"storeCode": m.get("storeCode"), "storeName": m.get("storeName", ""),
            "fetchedAt": m.get("fetchedAt", ""), "count": m.get("count", len(items)),
            "items": items}


def short_details():
    out = {}
    if not os.path.isdir(DETAILS):
        return out
    for fn in os.listdir(DETAILS):
        if not fn.endswith(".json"):
            continue
        d = json.load(open(os.path.join(DETAILS, fn), encoding="utf-8"))
        rounds = []
        for r in d.get("rounds", []):
            choices = []
            for c in r.get("choices", []):
                mods = []
                for it in (c.get("modification") or {}).get("items", []) or []:
                    for v in it.get("values", []) or []:
                        nm = v.get("name", "")
                        if nm and nm not in mods:
                            mods.append(nm)
                choices.append({
                    "c": c.get("code"), "n": c.get("name", ""),
                    "q": c.get("quantity") or 0,
                    "d": c.get("isDefault") or 0,
                    "dp": c.get("diffPrice") or "+ ¥0",
                    "m": 1 if c.get("supportModify") else 0,
                    "mods": mods,
                })
            rounds.append({"n": r.get("name", ""), "c": choices})
        out[fn[:-5]] = {"n": d.get("name", ""), "r": rounds}
    return out


def main():
    nut = short_nutrition()
    menu = short_menu()
    det = short_details()
    payload = {"nutrition": nut, "menu": menu, "details": det}

    factors = json.load(open(os.path.join(DATA, "factors.json"), encoding="utf-8"))
    taste = json.load(open(os.path.join(DATA, "taste.json"), encoding="utf-8"))
    zero = json.load(open(os.path.join(DATA, "zero_whitelist.json"), encoding="utf-8"))
    aliases = json.load(open(os.path.join(DATA, "aliases.json"), encoding="utf-8"))
    derived = json.load(open(os.path.join(DATA, "derived.json"), encoding="utf-8"))
    payload["taste"] = taste
    payload["zero"] = zero.get("names", [])
    payload["aliases"] = aliases.get("aliases", {})
    payload["derived"] = derived.get("rules", {})
    payload["factors"] = {k: v for k, v in factors.items() if not k.startswith("_")}

    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    tpl_path = os.path.join(HERE, "template.html")
    tpl = open(tpl_path, encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", blob)

    out = os.path.join(HERE, "index.html")
    open(out, "w", encoding="utf-8").write(html)

    kb = os.path.getsize(out) / 1024
    print(f"营养表 {len(nut['rows'])} 行｜菜单 {len(menu['items'])} 个｜详情 {len(det)} 份")
    print(f"已生成 {out}｜{kb:.0f} KB")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
