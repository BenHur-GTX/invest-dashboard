"""10년물 실질금리(TIPS) 검증용 원자료 → data/tips_raw.json (11-20, 분석용, 화면 미사용)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "tips_raw.json")
FRED_IDS = ["DFII10", "FII10", "DGS10", "T10YIE", "FEDFUNDS", "UNRATE"]
YH = ["QQQ", "SPY", "^GSPC", "^NDX", "GLD", "GC=F", "BTC-USD", "^KS11", "^KQ11"]


def main():
    out = {"fred": {}, "yahoo": {}, "errors": []}
    for sid in FRED_IDS:
        for t in range(3):
            try:
                rows = fred(sid, "1990-01-01")
                out["fred"][sid] = [[d, v] for d, v in rows]
                print(sid, len(rows), rows[0], rows[-1], flush=True)
                break
            except Exception as e:  # noqa
                print("fail", sid, e, flush=True); time.sleep(3)
        else:
            out["errors"].append(sid)
    for sym in YH:
        try:
            rows = yahoo(sym, "max")
            out["yahoo"][sym] = [[r[0], round(r[4], 4)] for r in rows]
            print(sym, len(rows), rows[0][0], rows[-1][0], flush=True)
        except Exception as e:  # noqa
            print("fail", sym, e, flush=True); out["errors"].append(sym)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
