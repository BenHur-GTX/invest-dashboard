"""박종훈 금리 눈금·버블 지표 검증용 원자료 → data/park_raw.json (11-20, 분석용, 화면 미사용)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo, http_get  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "park_raw.json")
FRED_IDS = ["BOGMBASE", "IRLTLT01KRM156N", "GASREGW", "CUSR0000SETB01", "MORTGAGE30US",
            "MSPUS", "MEHOINUSA672N", "UMCSENT", "CPIAUCSL", "UNRATE", "GS10", "DGS10", "USREC",
            "WALCL", "CURRCIR"]


def main():
    out = {"fred": {}, "yahoo": {}, "gold": [], "errors": []}
    for sid in FRED_IDS:
        for t in range(3):
            try:
                rows = fred(sid, "1945-01-01")
                out["fred"][sid] = [[d, v] for d, v in rows]
                print(sid, len(rows), rows[0], rows[-1], flush=True)
                break
            except Exception as e:  # noqa
                print("fail", sid, e, flush=True); time.sleep(3)
        else:
            out["errors"].append(sid)
    for sym in ["^GSPC", "^SP500TR", "^NDX", "GC=F", "GLD", "^KS11"]:
        try:
            rows = yahoo(sym, "max")
            out["yahoo"][sym] = [[r[0], round(r[4], 4)] for r in rows]
            print(sym, len(rows), rows[0][0], rows[-1][0], flush=True)
        except Exception as e:  # noqa
            print("fail", sym, e, flush=True); out["errors"].append(sym)
    try:
        txt = http_get("https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv")
        if isinstance(txt, bytes):
            txt = txt.decode()
        for line in txt.strip().splitlines()[1:]:
            d, v = line.split(",")[:2]
            out["gold"].append([d, float(v)])
        print("gold", len(out["gold"]), out["gold"][0], out["gold"][-1])
    except Exception as e:  # noqa
        print("fail gold", e); out["errors"].append("gold")
    json.dump(out, open(OUT, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
