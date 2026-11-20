import json, time, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
out = {}
for s in ["QQQ", "SCHD"]:
    p2 = int(time.time()) + 86400; p1 = p2 - 86400 * 12
    t = urllib.request.urlopen(urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1={p1}&period2={p2}&interval=1d&includeAdjustedClose=true", headers={"User-Agent": UA}), timeout=20).read()
    j = json.loads(t)["chart"]["result"][0]
    out[s] = {"ts": j["timestamp"], "close": j["indicators"]["quote"][0]["close"], "meta": {k: j["meta"].get(k) for k in ("regularMarketTime", "regularMarketPrice", "fulldayPrice", "regularMarketDayHigh", "regularMarketDayLow", "regularMarketVolume")}}
json.dump(out, open("data/probe_ext.json", "w"))
