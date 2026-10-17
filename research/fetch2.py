import json, os, subprocess, sys

OUT = os.path.dirname(os.path.abspath(__file__))
RD = os.path.join(OUT, "readmes")
os.makedirs(RD, exist_ok=True)

ORDER = ["mcd-saver-strategist", "mcd-coupon-strategist", "mccarbon", "McOracle",
         "mcd-budget-meal", "McLife-Desk", "mcd-party-officer", "maimen-certification",
         "mcd-wrapped", "mcd-calorie-butler"]
resolved = json.load(open(os.path.join(OUT, "resolved.json"), encoding="utf-8"))

def curl(url, out=None, timeout=12):
    cmd = ["curl", "-sL", "-m", str(timeout), "-w", "%{http_code}"]
    if out:
        cmd += ["-o", out]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip(), (os.path.getsize(out) if out and os.path.exists(out) else 0)

meta_path = os.path.join(OUT, "meta.json")
meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}

for name in ORDER:
    full = resolved[name]
    m = meta.get(name, {"full_name": full})
    if "language" not in m:
        code, _ = curl(f"https://api.github.com/repos/{full}", os.path.join(OUT, "_repo.json"))
        if code == "200":
            d = json.load(open(os.path.join(OUT, "_repo.json"), encoding="utf-8"))
            m = {k: d.get(k) for k in ("full_name", "description", "language", "size",
                                       "stargazers_count", "created_at", "pushed_at", "topics")}
            lic = d.get("license") or {}
            m["license"] = lic.get("spdx_id")
            m["homepage"] = d.get("homepage")
    target = os.path.join(RD, f"{name}.md")
    if not (os.path.exists(target) and os.path.getsize(target) > 200):
        found = False
        for ref in ("HEAD", "main", "master"):
            for fn in ("README.md", "README_EN.md", "README.zh-CN.md"):
                code, size = curl(f"https://raw.githubusercontent.com/{full}/{ref}/{fn}", target)
                if code == "200" and size > 200:
                    m["readme_file"] = f"{ref}/{fn}"
                    m["readme_bytes"] = size
                    found = True
                    break
            if found:
                break
        if not found:
            m["readme_bytes"] = 0
    meta[name] = m
    print(f"{name:26} {str(m.get('language')):9} {str(m.get('stargazers_count')):>5} "
          f"{str(m.get('readme_bytes')):>7}B  {str(m.get('created_at'))[:10]}", flush=True)
    json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("\ndone ->", RD, flush=True)
