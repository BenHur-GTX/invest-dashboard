"""하락 예고 지표 점검용 원자료 덤프 → data/warn_raw.json (11-20, 검증 후 삭제)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo, http_get  # noqa
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "warn_raw.json")
FIDS = ["VIXCLS", "DRTSCILM", "DRBLACBS", "NFCI", "M2SL", "CPIAUCSL", "BAA10Y", "DGS10", "ICSA", "SAHMREALTIME", "UNRATE"]
YS = ["QQQ", "^VIX", "ARCC", "BIZD", "HYG", "^GSPC"]
out = {"fred": {}, "yahoo": {}, "fg": None, "errors": []}
for sid in FIDS:
    for t in range(3):
        try:
            rows = fred(sid, "1990-01-01"); out["fred"][sid] = [[d, v] for d, v in rows]; print(sid, len(rows), flush=True); break
        except Exception as e:
            print("fail", sid, e, flush=True); time.sleep(3)
    else: out["errors"].append(sid)
for s in YS:
    try:
        rows = yahoo(s, "max"); out["yahoo"][s] = [[r[0], round(r[2], 4), round(r[3], 4), round(r[5], 4)] for r in rows]; print(s, len(rows), flush=True)
    except Exception as e:
        print("fail", s, e, flush=True); out["errors"].append(s)
try:
    j = json.loads(http_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2010-01-01", tries=2, headers={"Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}))
    out["fg"] = [[int(p["x"]), p["y"]] for p in j["fear_and_greed_historical"]["data"]]; print("fg", len(out["fg"]))
except Exception as e:
    print("fail fg", e); out["errors"].append("fg")
json.dump(out, open(OUT, "w"), separators=(",", ":"))
