import json, time, urllib.request, urllib.error, urllib.parse, os, sys

OUT = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "wb-research", "Accept": "application/vnd.github+json"}

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def api(url):
    return json.loads(get(url))

# 榜单前 10（除已确认的 3 个）需要反查 owner/repo
SEARCH = [
    "mcd-coupon-strategist",
    "mccarbon",
    "McOracle",
    "mcd-budget-meal",
    "mcd-party-officer",
    "maimen-certification",
    "mcd-wrapped",
]

KNOWN = {
    "mcd-saver-strategist": "hujjun/mcd-saver-strategist",
    "McLife-Desk": "Nikii-w/McLife-Desk",
    "mcd-calorie-butler": "WilderNoTrack/mcd-calorie-butler",
}

resolved = dict(KNOWN)
for i, name in enumerate(SEARCH):
    if i:
        time.sleep(7)
    try:
        d = api(f"https://api.github.com/search/repositories?q={urllib.parse.quote(name)}+in:name&per_page=5")
        items = d.get("items", [])
        hit = None
        for it in items:
            if it["name"].lower() == name.lower():
                hit = it
                break
        if hit:
            resolved[name] = hit["full_name"]
            print(f"OK   {name} -> {hit['full_name']} ({hit['stargazers_count']}star, {hit.get('language')})")
        else:
            print(f"MISS {name} -> candidates: {[it['full_name'] for it in items]}")
    except urllib.error.HTTPError as e:
        print(f"ERR  {name} -> HTTP {e.code}")
    except Exception as e:
        print(f"ERR  {name} -> {e}")

with open(os.path.join(OUT, "resolved.json"), "w", encoding="utf-8") as f:
    json.dump(resolved, f, ensure_ascii=False, indent=2)
print("\nresolved:", len(resolved))
