"""임시: 데드크로스 스윙 변형 검증용 원자료(금·JEPI·JEPQ·SPY·CNN 공포탐욕 이력) → data/_dc_raw.json. 검증 후 삭제."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from build_data import yahoo, http_get  # noqa
out = {"yahoo": {}, "fng": {}, "errors": []}
for s in ["GC=F", "GLD", "SPY", "JEPI", "JEPQ", "QQQ"]:
    try:
        r = yahoo(s, "max"); out["yahoo"][s] = [[x[0], round(x[4], 4), round(x[5], 4)] for x in r]; print(s, len(r), r[0][0], flush=True)
    except Exception as e:
        out["errors"].append(f"{s} {e}"); print("fail", s, e, flush=True)
for start in ["2011-01-01", "2018-01-01", "2020-07-15", "2021-01-01"]:
    try:
        j = json.loads(http_get(f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}", tries=2, headers={"Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}))
        h = j.get("fear_and_greed_historical", {}).get("data", [])
        out["fng"][start] = [[x["x"], x["y"]] for x in h]; print("fng", start, len(h), flush=True)
    except Exception as e:
        out["errors"].append(f"fng {start} {e}"); print("fail fng", start, e, flush=True)
json.dump(out, open(os.path.join(os.path.dirname(__file__), "..", "data", "_dc_raw.json"), "w"), separators=(",", ":"))
