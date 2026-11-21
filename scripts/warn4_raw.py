"""임시(11-21): MOVE·SKEW·기간 프리미엄 원자료 덤프 → data/warn4_raw.json (검증 후 삭제)"""
import json, os, sys, base64
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo, http_get  # noqa
out = {"yahoo": {}, "fred": {}, "errors": [], "raw": {}}
for s in ("^MOVE", "^SKEW", "^VIX", "QQQ", "^GSPC", "^NDX"):
    try: out["yahoo"][s] = [[r[0], r[4]] for r in yahoo(s, "max")]
    except Exception as e: out["errors"].append(f"{s}: {e}")
for s in ("THREENFTP10", "BAMLH0A0HYM2", "DGS10", "BAA10Y", "VIXCLS"):
    try: out["fred"][s] = fred(s, "1985-01-01")
    except Exception as e: out["errors"].append(f"{s}: {e}")
for k, u in (("skew_cboe", "https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv"),
             ("acm", "https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls")):
    try:
        import urllib.request
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        b = urllib.request.urlopen(req, timeout=60).read()
        out["raw"][k] = base64.b64encode(b).decode()
    except Exception as e: out["errors"].append(f"{k}: {e}")
print({k: len(v) for k, v in out["yahoo"].items()}, {k: len(v) for k, v in out["fred"].items()}, {k: len(v) for k, v in out["raw"].items()}, out["errors"])
json.dump(out, open(os.path.join(os.path.dirname(__file__), "..", "data", "warn4_raw.json"), "w"))
