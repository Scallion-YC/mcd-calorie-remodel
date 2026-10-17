#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心引擎：营养对齐 → 组件汇总 → 硬约束过滤 → 排序 → 改造建议 → 方案卡。

零第三方依赖。所有数值来自 data/ 下的快照，不联网。
设计依据：产品需求手册.md §4–§9
"""

import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DETAILS = os.path.join(DATA, "details")

MODES = {
    "cut":    {"label": "减脂", "key": "density", "protein_g_per_kg": 1.6},
    "bulk":   {"label": "增肌", "key": "protein_per_yuan", "protein_g_per_kg": 1.8},
    "keep":   {"label": "维持", "key": "band", "protein_g_per_kg": 0.0},
}


# ---------------------------------------------------------------- 数据加载

def _read(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    return json.load(open(p, encoding="utf-8"))


def load_nutrition():
    d = _read("nutrition.json", {"rows": [], "fetchedAt": ""})
    return d.get("rows", []), d.get("fetchedAt", "")


def load_menu():
    return _read("menu.json", {})


def load_details():
    out = {}
    if not os.path.isdir(DETAILS):
        return out
    for fn in os.listdir(DETAILS):
        if fn.endswith(".json"):
            out[fn[:-5]] = json.load(open(os.path.join(DETAILS, fn), encoding="utf-8"))
    return out


def load_factors():
    return _read("factors.json", {})


def load_taste():
    return _read("taste.json", {}).get("weights", {})


def load_zero_whitelist():
    return set(_read("zero_whitelist.json", {}).get("names", []))


def load_aliases():
    d = _read("aliases.json", {})
    return {norm(k): norm(v) for k, v in (d.get("aliases") or {}).items()}


def load_derived():
    d = _read("derived.json", {})
    return {norm(k): v for k, v in (d.get("rules") or {}).items()}


def load_estimates():
    d = _read("estimates.json", {})
    return d.get("items") or {}


def estimate(name, book, table):
    """当季新品的区间估算。返回 None 表示没有可用锚点。"""
    rule = table.get(name)
    if not rule:
        return None
    row = book.get(rule.get("anchor", ""))
    if not row:
        return None
    k = num(row.get("kcal")) or 0.0
    p = num(row.get("protein")) or 0.0
    try:
        f = float(rule.get("factor", 1))
        pf = float(rule.get("protein_factor", 1))
        band = float(rule.get("band", 0.15))
    except (TypeError, ValueError):
        return None
    mid = k * f
    pmid = p * pf
    return {
        "name": name, "anchor": rule.get("anchor", ""), "why": rule.get("why", ""),
        "band": band,
        "kcal_mid": round(mid), "kcal_lo": round(mid * (1 - band)), "kcal_hi": round(mid * (1 + band)),
        "protein_mid": round(pmid, 1), "protein_lo": round(pmid * (1 - band), 1),
        "protein_hi": round(pmid * (1 + band), 1),
    }


# ---------------------------------------------------------------- 对齐

def norm(s):
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"[\s\u3000]", "", s)
    return s


def num(v):
    """营养值转 float。'null' / 空串 / 非法 → None。"""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "null", "None", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


class Book:
    """营养表。按名称对齐，重名取第一条；别名处理命名差异，倍数规则处理离散件数。"""

    def __init__(self, rows, aliases=None, derived=None):
        self.rows = rows
        self.index = {}
        self.dups = []
        self.aliases = aliases or {}
        self.derived = derived or {}
        self.alias_hits = []
        for r in rows:
            k = norm(r["name"])
            if k in self.index:
                self.dups.append(r["name"])
                continue
            self.index[k] = r

    def resolve(self, name):
        """返回 (row, 'exact'|'alias'|'derived') 或 (None, None)。"""
        k = norm(name)
        if k in self.index:
            return self.index[k], "exact"
        target = self.aliases.get(k)
        if target and target in self.index:
            self.alias_hits.append(name)
            return self.index[target], "alias"
        rule = self.derived.get(k)
        if rule:
            base = self.index.get(norm(rule.get("base", "")))
            try:
                f = float(rule.get("factor", 1))
            except (TypeError, ValueError):
                f = 1.0
            if base:
                row = dict(base)
                row["name"] = name
                for fld in ("kj", "kcal", "protein", "fat", "carb", "sodium", "calcium"):
                    v = num(base.get(fld))
                    row[fld] = "" if v is None else round(v * f, 1)
                return row, "derived"
        return None, None

    def get(self, name):
        return self.resolve(name)[0]

    def macro(self, name, zero_ok):
        """返回 (kcal, protein, sodium) 或 None。全 None 视为缺失。"""
        row, _ = self.resolve(name)
        return macro_row(row, name, zero_ok)


def macro_row(r, name, zero_ok):
    if not r:
        return None
    k, p, s = num(r.get("kcal")), num(r.get("protein")), num(r.get("sodium"))
    if k is None and p is None and s is None:
        return None
    if k == 0 and norm(name) not in zero_ok:
        # 0 卡但不在白名单：不信任，视为 unknown
        return None
    return (k or 0.0, p or 0.0, s or 0.0)


# ---------------------------------------------------------------- 套餐结构

def default_components(detail):
    """取每轮次 isDefault=1（或 quantity>0）的选项，返回组件列表。"""
    comps = []
    for rnd in detail.get("rounds", []) or []:
        choices = rnd.get("choices", []) or []
        picked = [c for c in choices if c.get("isDefault") == 1]
        if not picked:
            picked = [c for c in choices if (c.get("quantity") or 0) > 0]
        if not picked and choices:
            picked = [choices[0]]
        for c in picked:
            comps.append({
                "round": rnd.get("name", ""),
                "code": c.get("code"),
                "name": c.get("name", ""),
                "qty": c.get("quantity") or 1,
            })
    return comps


def price_of(menu_item):
    v = num(menu_item.get("currentPrice"))
    return v if v is not None else None


def parse_diff(s):
    """'+ ¥2' / '- ¥0.5' / '+ ¥0' → float"""
    if s is None:
        return 0.0
    t = str(s).replace("¥", "").replace("￥", "").replace(" ", "")
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", t)
    if not m:
        return 0.0
    return float(m.group(1))


class Combo:
    """一个套餐的营养与价格汇总。"""

    def __init__(self, code, item, detail, book, zero_ok):
        self.code = code
        self.name = item.get("name", "")
        self.base_price = price_of(item)
        self.detail = detail or {}
        self.comps = default_components(self.detail) if detail else []
        self.rows = []          # [(comp, macro|None)]
        self.kcal = 0.0
        self.protein = 0.0
        self.sodium = 0.0
        self.missing = []
        self.alias_comp = 0
        self.derived_comp = 0
        for c in self.comps:
            row, src = book.resolve(c["name"])
            m = macro_row(row, c["name"], zero_ok)
            if src == "alias":
                self.alias_comp += 1
            elif src == "derived":
                self.derived_comp += 1
            self.rows.append((c, m))
            if m is None:
                self.missing.append(c["name"])
            else:
                self.kcal += m[0] * c["qty"]
                self.protein += m[1] * c["qty"]
                self.sodium += m[2] * c["qty"]
        self.total_comp = len(self.comps)
        self.hit_comp = self.total_comp - len(self.missing)

    # ---- 指标
    @property
    def status(self):
        if self.total_comp == 0:
            return "unknown"
        return "exact" if not self.missing else "partial"

    @property
    def density(self):
        return round(self.protein / self.kcal * 100, 2) if self.kcal else 0.0

    @property
    def protein_per_yuan(self):
        return round(self.protein / self.base_price, 2) if self.base_price else 0.0

    @property
    def sodium_pct(self):
        return round(self.sodium / 2000 * 100, 0)

    @property
    def has_main(self):
        """是否含主食。只有饮料/小食的组合不进推荐。"""
        kw = ("堡", "卷", "鸡", "鱼", "牛", "猪", "饭", "沙拉", "肉")
        return any(any(k in c["name"] for k in kw) for c in self.comps)


# ---------------------------------------------------------------- 改造建议

def taste_cost(name, weights, default=3):
    for k, v in weights.items():
        if k in str(name):
            return v
    return default


def round_choices(detail):
    """[(roundName, defaultChoice, [其它 choices])]"""
    out = []
    for rnd in detail.get("rounds", []) or []:
        ch = rnd.get("choices", []) or []
        deft = next((c for c in ch if c.get("isDefault") == 1), None)
        if not deft:
            continue
        out.append((rnd.get("name", ""), deft, [c for c in ch if c is not deft]))
    return out


def suggestions(combo, book, zero_ok, mode, cap, taste, limit=3):
    """
    同轮次内替换，算四项差值。只保留：
      减脂：热量下降 且 改后仍达标 且 差价 <= 0
      增肌：蛋白上升 且 改后热量仍在区间内
    返回按「收益 / 口感代价」排序的前 limit 条。
    """
    out = []
    for rname, deft, alts in round_choices(combo.detail):
        dm = book.macro(deft.get("name", ""), zero_ok)
        if dm is None:
            continue
        for alt in alts:
            am = book.macro(alt.get("name", ""), zero_ok)
            if am is None:
                continue
            dk = am[0] - dm[0]
            dp = am[1] - dm[1]
            ds = am[2] - dm[2]
            dprice = parse_diff(alt.get("diffPrice")) - parse_diff(deft.get("diffPrice"))
            new_kcal = combo.kcal + dk
            new_protein = combo.protein + dp

            if mode == "cut":
                if dk >= 0 or new_kcal > cap or dprice > 0:
                    continue
                benefit = (-dk) / 100.0
            elif mode == "bulk":
                # 蛋白增益要扣价格代价，且低于 2 g 的替换不值得提
                if dp < 2 or new_kcal > cap:
                    continue
                benefit = dp / (1 + max(dprice, 0) / 5.0)
            else:
                if dk >= 0:
                    continue
                benefit = (-dk) / 200.0

            cost = taste_cost(alt.get("name", ""), taste)
            out.append({
                "round": rname,
                "from": deft.get("name", ""),
                "to": alt.get("name", ""),
                "d_kcal": round(dk, 1),
                "d_protein": round(dp, 1),
                "d_sodium": round(ds, 0),
                "d_price": round(dprice, 2),
                "tag": "exact",
                "score": round(benefit / cost, 3),
            })
    out.sort(key=lambda x: -x["score"])
    # 同一轮次只留一条最优；减脂模式限制累计降幅，避免把一餐砍到不合理的程度
    seen, picked = set(), []
    cum_k, cum_p = 0.0, 0.0
    for s in out:
        if s["round"] in seen:
            continue
        if mode == "cut":
            new_k = combo.kcal + cum_k + s["d_kcal"]
            drop = -(cum_k + s["d_kcal"])
            if drop > 0.3 * combo.kcal or new_k < 400:
                continue
            new_p = combo.protein + cum_p + s["d_protein"]
            if new_p / new_k < combo.protein / combo.kcal:  # 蛋白密度不得下降
                continue
        seen.add(s["round"])
        picked.append(s)
        cum_k += s["d_kcal"]
        cum_p += s["d_protein"]
        if len(picked) >= limit:
            break
    return picked


def modification_notes(combo, factors, limit=3):
    """特调建议。factors 里没有可靠数值的一律不参与计算。"""
    notes = []
    for comp in combo.comps:
        mod = None
        # 详情里组件自带 modification
        for rnd in combo.detail.get("rounds", []) or []:
            for c in rnd.get("choices", []) or []:
                if c.get("code") == comp["code"]:
                    mod = c.get("modification")
        if not mod:
            continue
        for item in mod.get("items", []) or []:
            for v in item.get("values", []) or []:
                name = v.get("name", "")
                f = factors.get(name)
                if not f or f.get("kcal") is None:
                    continue
                notes.append({"target": comp["name"], "name": name,
                              "d_kcal": -f["kcal"],
                              "d_sodium": (-f["sodium"] if f.get("sodium") is not None else None),
                              "unit": f.get("unit", ""),
                              "tag": "估算", "confidence": f.get("confidence", "low")})
    return notes[:limit]


# ---------------------------------------------------------------- 求解

MULTI_KW = ("分享", "双人", "多人", "拼盘", "拼单")


def candidates(menu, details, book, zero_ok):
    out = []
    for code, item in (menu.get("items") or {}).items():
        d = details.get(code)
        if not d:
            continue
        c = Combo(code, item, d, book, zero_ok)
        if c.status != "exact" or not c.has_main:
            continue
        if any(k in c.name for k in MULTI_KW):
            continue
        out.append(c)
    return out


def solve(mode, cap, protein_floor, menu, details, book, zero_ok, top=3):
    """
    硬约束先过滤，再按模式主键排序。
    若无人同时满足，降级而不是返回空：
      protein_short —— 热量达标但蛋白不够，取蛋白最高的
      kcal_over     —— 连热量都超，取最接近额度的
    返回 (plans, pool, state)
    """
    pool = candidates(menu, details, book, zero_ok)
    # 维持模式按 ±10% 的区间判，其余按上限判
    limit = cap * 1.1 if mode == "keep" else cap
    within = [c for c in pool if c.kcal <= limit]
    passed = [c for c in within if not protein_floor or c.protein >= protein_floor]

    key = MODES[mode]["key"]

    def sort_by_key(lst):
        if key == "density":
            lst.sort(key=lambda c: -c.density)
        elif key == "protein_per_yuan":
            lst.sort(key=lambda c: -c.protein_per_yuan)
        elif key == "band":
            lst.sort(key=lambda c: (abs(c.kcal - cap), c.base_price or 9e9))
        else:
            lst.sort(key=lambda c: (c.base_price if c.base_price is not None else 9e9))
        return lst

    if passed:
        return sort_by_key(passed)[:top], pool, "ok"

    if within:
        within.sort(key=lambda c: (-c.protein, c.kcal))
        return within[:top], pool, "protein_short"

    pool.sort(key=lambda c: c.kcal)
    return pool[:top], pool, "kcal_over"


def protein_floor_for(mode, weight, meals=3):
    g = MODES[mode]["protein_g_per_kg"]
    if not g or not weight:
        return 0.0
    return round(g * weight / max(meals, 1), 1)


# ---------------------------------------------------------------- 渲染

def reason_of(mode, state):
    if state == "protein_short":
        return "这个额度内热量达标、蛋白最高的一个"
    if state == "kcal_over":
        return "所有套餐里热量最低的一个"
    return {"cut": "同额度内蛋白密度最高", "bulk": "同额度内蛋白性价比最高",
            "keep": "最接近你给的额度"}.get(mode, "")


def render(combo, sugg, notes, mode, cap, protein_floor, state="ok"):
    L = []
    head = f"【{MODES[mode]['label']} · 本餐】额度 {cap:.0f} kcal"
    if protein_floor:
        head += f" · 蛋白目标 {protein_floor:g} g"
    L.append(head)
    L.append("─" * 40)

    if state == "protein_short":
        L.append(f"⚠ 这个额度内没有套餐能达到蛋白 {protein_floor:g} g"
                 f"（当前最高 {combo.protein:.0f} g）。以下为最接近的方案，缺口照实列出。")
        L.append("")
    elif state == "kcal_over":
        L.append(f"⚠ 没有套餐低于 {cap:.0f} kcal（最低 {combo.kcal:.0f} kcal）。"
                 "以下为热量最低的方案，已超出你的额度。")
        L.append("")

    names = " + ".join(c["name"] for c in combo.comps)
    L.append(f"推荐：{combo.name}")
    L.append(f"理由：{reason_of(mode, state)}")
    L.append(f"组成：{names}")
    price = f"¥{combo.base_price:.1f}" if combo.base_price is not None else "价格未知"
    L.append(f"实付 {price}（菜单价）· 热量 {combo.kcal:.0f} kcal · 蛋白 {combo.protein:.0f} g")
    L.append(f"蛋白密度 {combo.density} g/100kcal · 钠 {combo.sodium:.0f} mg（{combo.sodium_pct:.0f}% 日参考）")
    tag = f"exact {combo.hit_comp}/{combo.total_comp} 组件"
    if combo.derived_comp:
        tag += f"（含 {combo.derived_comp} 项按倍数推导）"
    L.append(f"数据：{tag}")

    fin_k = combo.kcal
    fin_p = combo.protein
    fin_price = combo.base_price or 0.0

    if sugg:
        L.append("")
        L.append(f"改这 {len(sugg)} 处：")
        for i, s in enumerate(sugg, 1):
            seg = f"{i}. {s['from']}→{s['to']}"
            seg += f"  {s['d_kcal']:+.0f} kcal  {s['d_protein']:+.0f} g 蛋白  {s['d_sodium']:+.0f} mg 钠"
            seg += f"  {s['d_price']:+.1f} 元"
            L.append(seg)
        fin_k = combo.kcal + sum(s["d_kcal"] for s in sugg)
        fin_p = combo.protein + sum(s["d_protein"] for s in sugg)
        fin_price = (combo.base_price or 0) + sum(s["d_price"] for s in sugg)
        L.append("")
        L.append(f"改完：{fin_k:.0f} kcal · 蛋白 {fin_p:.0f} g · ¥{fin_price:.1f}")

    if notes:
        L.append("")
        L.append("可特调（估算值，跨市场参考，未与上方数值相加）：")
        for n in notes:
            unit = f"（1 {n['unit']}）" if n.get("unit") else ""
            seg = f"  · {n['target']} 去{n['name']}{unit}  {n['d_kcal']:+.0f} kcal"
            if n.get("d_sodium") is not None:
                seg += f"  {n['d_sodium']:+.0f} mg 钠"
            seg += f"  [{n['tag']}·{n['confidence']}]"
            L.append(seg)

    if protein_floor and fin_p < protein_floor:
        tail = "（同轮次替换补不齐，需另加一份高蛋白单点）" if mode == "bulk" \
            else "（麦当劳单餐补不齐，需另加蛋白来源）"
        L.append(f"蛋白缺口 {protein_floor - fin_p:.1f} g{tail}")
    elif protein_floor and sugg:
        L.append(f"改完蛋白达标（目标 {protein_floor:g} g）")
    if state == "kcal_over":
        L.append(f"⚠ 没有套餐低于 {cap:.0f} kcal，以上为热量最低的方案")
    return "\n".join(L)
