"""Threads 폭락 체크리스트(11개 지표) 1주 전 신호 검증용 원자료 덤프 → data/crash_raw.json (임시)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "crash_raw.json")
FRED_IDS = ["DGS10", "DGS2", "DFEDTARU", "DFEDTAR", "BAMLH0A0HYM2", "BAA10Y", "UNRATE", "CPILFESL",
            "SAHMREALTIME", "IC4WSA", "ICSA", "NFCI", "DEXJPUS", "DEXKOUS", "VIXCLS"]
YH = ["^GSPC", "^KS11", "^VIX", "QQQ", "JPY=X", "KRW=X",
      "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "RSP", "SPY"]


def main():
    out = {"fred": {}, "yahoo": {}, "errors": []}
    for sid in FRED_IDS:
        for t in range(3):
            try:
                rows = fred(sid, "1985-01-01")
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
