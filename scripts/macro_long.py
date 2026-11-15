"""장기 거시 시계열: 기준금리 · M2 · CPI · 근원 CPI · 연준 순유동성(월평균) → data/macro_long.json
FRED 무료. 주 1회 갱신이면 충분 (월간 지표).
"""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred  # noqa

START = "1959-01-01"


def monthly(rows):
    acc = defaultdict(list)
    for d, v in rows:
        acc[d[:7]].append(v)
    return {k: sum(v) / len(v) for k, v in sorted(acc.items())}


def main():
    s = {}
    for k, sid, st in [("ff", "FEDFUNDS", START), ("m2", "M2SL", START), ("cpi", "CPIAUCSL", START),
                       ("core", "CPILFESL", START), ("walcl", "WALCL", "2002-12-01"),
                       ("tga", "WTREGEN", "2002-12-01"), ("rrp", "RRPONTSYD", "2002-12-01"),
                       ("pce", "PCEPILFE", START)]:
        s[k] = monthly(fred(sid, st))
        print(k, len(s[k]), list(s[k].items())[-1])
    months = sorted(set(s["m2"]) | set(s["cpi"]) | set(s["ff"]))
    nl = {}
    for m in s["walcl"]:
        if m in s["tga"]:
            # WALCL·WTREGEN 백만$, RRP 십억$ → 십억$
            nl[m] = s["walcl"][m] / 1000 - s["tga"][m] / 1000 - s["rrp"].get(m, 0)
    out = {"months": months}
    for k in ["ff", "m2", "cpi", "core", "pce"]:
        out[k] = [round(s[k][m], 4) if m in s[k] else None for m in months]
    out["netliq"] = [round(nl[m], 1) if m in nl else None for m in months]
    os.makedirs("data", exist_ok=True)
    json.dump(out, open("data/macro_long.json", "w"), separators=(",", ":"))
    print("ok", len(months))


if __name__ == "__main__":
    main()
