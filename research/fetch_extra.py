import json, os, subprocess, time, urllib.parse

OUT = os.path.dirname(os.path.abspath(__file__))
RD = os.path.join(OUT, "readmes")
os.makedirs(RD, exist_ok=True)

TARGETS = ["mcd-order-calories", "mcd-calorie-budget-skill", "mcd-fit-planner",
           "mcd-100kcal", "mcd-calorie-skill", "walk-kcal"]

def curl(url, out=None, timeout=15):
    cmd = ["curl", "-sL", "-m", str(timeout), "-w", "%{http_code}"]
    if out:
        cmd += ["-o", out]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip(), (os.path.getsize(out) if out and os.path.exists(out) else 0)

extra = {}
for i, name in enumerate(TARGETS):
    if i:
        time.sleep(7)
    tmp = os.path.join(OUT, "_s.json")
    code, _ = curl(f"https://api.github.com/search/repositories?q={urllib.parse.quote(name)}+in:name&per_page=5", tmp)
    if code != "200":
        print(f"ERR {name} HTTP {code}", flush=True)
        continue
    items = json.load(open(tmp, encoding="utf-8")).get("items", [])
    hit = next((it for it in items if it["name"].lower() == name.lower()), None)
    if not hit:
        print(f"MISS {name} -> {[it['full_name'] for it in items]}", flush=True)
        continue
    full = hit["full_name"]
    target = os.path.join(RD, f"{name}.md")
    got = False
    for ref in ("HEAD", "main", "master"):
        for fn in ("README.md", "README_EN.md"):
            c, s = curl(f"https://raw.githubusercontent.com/{full}/{ref}/{fn}", target)
            if c == "200" and s > 200:
                got = True
                break
        if got:
            break
    extra[name] = {"full_name": full, "stars": hit["stargazers_count"], "language": hit.get("language"),
                   "description": hit.get("description"), "bytes": os.path.getsize(target) if got else 0,
                   "created_at": hit.get("created_at")}
    print(f"{name:26} {full:40} {hit['stargazers_count']:>4}★  {extra[name]['bytes']}B", flush=True)

p = os.path.join(OUT, "extra.json")
old = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
old.update(extra)
json.dump(old, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("done", flush=True)
