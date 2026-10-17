import json, time, urllib.request, urllib.error, os

OUT = os.path.dirname(os.path.abspath(__file__))
RD = os.path.join(OUT, "readmes")
os.makedirs(RD, exist_ok=True)
UA = {"User-Agent": "wb-research", "Accept": "application/vnd.github+json"}

resolved = json.load(open(os.path.join(OUT, "resolved.json"), encoding="utf-8"))
# 榜单顺序
ORDER = ["mcd-saver-strategist", "mcd-coupon-strategist", "mccarbon", "McOracle",
         "mcd-budget-meal", "McLife-Desk", "mcd-party-officer", "maimen-certification",
         "mcd-wrapped", "mcd-calorie-butler"]

def get(url, raw=False, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "wb-research"} if raw else UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

meta = {}
for i, name in enumerate(ORDER):
    full = resolved[name]
    if i:
        time.sleep(1)
    m = {}
    try:
        d = json.loads(get(f"https://api.github.com/repos/{full}"))
        m = {k: d.get(k) for k in ("full_name","description","language","size","stargazers_count",
                                   "created_at","pushed_at","topics","license","fork","homepage")}
        if m.get("license"):
            m["license"] = m["license"].get("spdx_id")
    except Exception as e:
        m = {"full_name": full, "error": str(e)}

    text = None
    for ref in ("HEAD", "main", "master"):
        for fn in ("README.md", "readme.md", "README.zh-CN.md", "README_zh.md"):
            try:
                t = get(f"https://raw.githubusercontent.com/{full}/{ref}/{fn}", raw=True)
                if t.strip():
                    text = t
                    m["readme_file"] = f"{ref}/{fn}"
                    break
            except Exception:
                continue
        if text:
            break
    m["readme_bytes"] = len(text.encode("utf-8")) if text else 0
    meta[name] = m
    if text:
        safe = name.replace("/", "_")
        open(os.path.join(RD, f"{safe}.md"), "w", encoding="utf-8").write(text)
    print(f"{name:28} {m.get('language')!s:10} {m.get('stargazers_count')!s:5} "
          f"{m.get('readme_bytes')!s:7}B  created={str(m.get('created_at'))[:10]}")

json.dump(meta, open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\nreadmes ->", RD)
