"""장기 거시 시계열: 기준금리 · M2 · CPI · 근원 CPI · 연준 순유동성(월평균) → data/macro_long.json
FRED 무료. 주 1회 갱신이면 충분 (월간 지표).
"""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, http_get  # noqa
import datetime

START = "1959-01-01"


def monthly(rows):
    acc = defaultdict(list)
    for d, v in rows:
        acc[d[:7]].append(v)
    return {k: sum(v) / len(v) for k, v in sorted(acc.items())}


def ecos_m2(start="2000-01"):
    """한국 M2 (한국은행 ECOS 161Y005 BBHS00, 평잔·계절조정, 십억원).
    ECOS_API_KEY가 없으면 공개 sample 키(요청당 10건)로 10개월씩 나눠 받는다."""
    key = os.environ.get("ECOS_API_KEY") or "sample"
    y, m = int(start[:4]), int(start[5:7]); today = datetime.date.today(); out = {}
    step = 10 if key == "sample" else 400
    while (y, m) <= (today.year, today.month):
        ey, em = y + (m - 1 + step - 1) // 12, (m - 1 + step - 1) % 12 + 1
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/{step}/161Y005/M/{y}{m:02d}/{ey}{em:02d}/BBHS00"
        try:
            j = json.loads(http_get(url))
            for r in j.get("StatisticSearch", {}).get("row", []):
                out[r["TIME"][:4] + "-" + r["TIME"][4:6]] = float(r["DATA_VALUE"])
        except Exception as e:  # noqa
            print("ecos err", y, m, e)
        y, m = ey + (em // 12), em % 12 + 1
    return dict(sorted(out.items()))


def main():
    s = {}
    for k, sid, st in [("ff", "FEDFUNDS", START), ("m2", "M2SL", START), ("cpi", "CPIAUCSL", START),
                       ("core", "CPILFESL", START), ("walcl", "WALCL", "2002-12-01"),
                       ("tga", "WTREGEN", "2002-12-01"), ("rrp", "RRPONTSYD", "2002-12-01"),
                       ("pce", "PCEPILFE", START)]:
        s[k] = monthly(fred(sid, st))
        print(k, len(s[k]), list(s[k].items())[-1])
    try:
        s["krm2"] = ecos_m2()
        print("krm2", len(s["krm2"]), list(s["krm2"].items())[-1] if s["krm2"] else None)
    except Exception as e:  # noqa
        print("krm2 실패", e); s["krm2"] = {}
    months = sorted(set(s["m2"]) | set(s["cpi"]) | set(s["ff"]))
    nl = {}
    for m in s["walcl"]:
        if m in s["tga"]:
            # WALCL·WTREGEN 백만$, RRP 십억$ → 십억$
            nl[m] = s["walcl"][m] / 1000 - s["tga"][m] / 1000 - s["rrp"].get(m, 0)
    out = {"months": months}
    for k in ["ff", "m2", "cpi", "core", "pce", "krm2"]:
        out[k] = [round(s[k][m], 4) if m in s[k] else None for m in months]
    out["netliq"] = [round(nl[m], 1) if m in nl else None for m in months]
    os.makedirs("data", exist_ok=True)
    json.dump(out, open("data/macro_long.json", "w"), separators=(",", ":"))
    print("ok", len(months))


if __name__ == "__main__":
    main()
