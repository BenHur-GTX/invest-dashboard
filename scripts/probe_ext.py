import json, urllib.request, time
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
def get(url, h=None):
    hh = {"User-Agent": UA, "Accept": "*/*"}; hh.update(h or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hh), timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR", repr(e)[:300]
out = {"now": time.time()}
for s in ["QQQ", "QLD", "NVDA", "NQ=F", "ES=F"]:
    st, t = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=2d&interval=5m&includePrePost=true")
    try:
        j = json.loads(t)["chart"]["result"][0]
        ts = j["timestamp"]; c = j["indicators"]["quote"][0]["close"]
        last = [(ts[i], c[i]) for i in range(len(ts)) if c[i] is not None][-5:]
        out[s] = {"meta": j["meta"], "last": last, "n": len(ts)}
    except Exception as e:
        out[s] = {"st": st, "err": repr(e), "body": t[:300]}
st, t = get("https://api.nasdaq.com/api/quote/QQQ/info?assetclass=etf", {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
out["nasdaq"] = {"st": st, "body": t[:3000]}
st, t = get("https://finance.yahoo.com/quote/QQQ/")
import re
out["yq_overnight"] = {"st": st, "hits": [t[max(0,m.start()-200):m.start()+300] for m in re.finditer(r"(?i)overnight", t)][:4]}
json.dump(out, open("data/probe_ext.json", "w"), indent=1, default=str)
print(json.dumps(out, default=str)[:3000])
