"""유동성 신호등(SOFR−IORB) 기준 검증용 원자료 덤프 → data/liq_raw.json (11-20, 검증 후 삭제)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "liq_raw.json")
IDS = ["SOFR", "IOER", "IORB", "EFFR", "RRPONTSYD", "WALCL", "WTREGEN", "DFEDTARU", "DGS2", "DGS10",
       "SAHMREALTIME", "UNRATE", "ICSA", "BAMLH0A0HYM2", "BAA10Y", "TB3MS"]


def main():
    out = {"fred": {}, "yahoo": {}, "errors": []}
    for sid in IDS:
        for t in range(3):
            try:
                rows = fred(sid, "2002-01-01")
                out["fred"][sid] = [[d, v] for d, v in rows]
                print(sid, len(rows), rows[0], rows[-1], flush=True); break
            except Exception as e:  # noqa
                print("fail", sid, e, flush=True); time.sleep(3)
        else:
            out["errors"].append(sid)
    for sym in ["QQQ", "QLD", "^GSPC", "^NDX"]:
        try:
            rows = yahoo(sym, "max")
            out["yahoo"][sym] = [[r[0], round(r[5], 4)] for r in rows]
            print(sym, len(rows), rows[0][0], rows[-1][0], flush=True)
        except Exception as e:  # noqa
            print("fail", sym, e, flush=True); out["errors"].append(sym)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
