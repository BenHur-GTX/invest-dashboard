"""도망 모드(주식 비중 대폭 축소) 지표 조합 검증용 원자료 덤프 → data/escape_raw.json
(11-18 Ben: 금리차 역전→정상화 후 침체 시차, 8~12년 폭락 주기설, 금리·인플레 사이클 국면)
분석은 로컬에서 이 파일로. FRED 무료 + Yahoo.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "escape_raw.json")
FRED_IDS = ["UNRATE", "SAHMREALTIME", "T10Y2Y", "T10Y3M", "GS10", "GS2", "TB3MS", "FEDFUNDS",
            "CPIAUCSL", "CPILFESL", "BAA10Y", "BAA", "AAA", "USREC", "ICSA", "PAYEMS", "INDPRO",
            "M2SL", "DFEDTARU", "NFCI"]


def main():
    out = {"fred": {}, "yahoo": {}, "errors": []}
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
    for sym in ["^GSPC", "^SP500TR", "^NDX", "QQQ", "^IXIC"]:
        try:
            rows = yahoo(sym, "max")
            out["yahoo"][sym] = [[r[0], round(r[4], 4), round(r[5], 4)] for r in rows]
            print(sym, len(rows), rows[0][0], rows[-1][0], flush=True)
        except Exception as e:  # noqa
            print("fail", sym, e, flush=True); out["errors"].append(sym)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
