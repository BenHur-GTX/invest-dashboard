"""10년 실질금리(TIPS, FRED DFII10)와 주식·금·비트코인 이후 수익 검증 (11-20 Ben 요청, 참고용)
주장: 실질금리 2.4% 위면 주식·금·비트 동반 약세, 2.4% 아래로 내려오면 '애브리씽 랠리'.
→ data/tips_study.json
"""
import json, os, sys, statistics as st
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "tips_study.json")
H = {"3m": 63, "6m": 126, "12m": 252}


def load():
    ry = dict(fred("DFII10", "2003-01-01"))
    nom = dict(fred("DGS10", "2003-01-01"))
    px = {}
    for k, s in (("spx", "^GSPC"), ("ndx", "QQQ"), ("gold", "GC=F"), ("btc", "BTC-USD")):
        try:
            px[k] = {r[0]: r[5] for r in yahoo(s, "max")}
        except Exception as e:  # noqa
            print("price fail", s, e)
    return ry, nom, px


def main():
    ry, nom, px = load()
    days = sorted(d for d in ry if d in px["spx"])     # 미국 거래일 기준
    idx = {d: i for i, d in enumerate(days)}
    # 비트코인은 주말도 있음 → 같은 날짜 값 사용
    def fwd(k, i, n):
        if i + n >= len(days):
            return None
        a, b = px[k].get(days[i]), px[k].get(days[i + n])
        return None if a is None or b is None else (b / a - 1) * 100

    def summ(sel, label):
        out = {"label": label, "n_days": len(sel)}
        for k in px:
            for h, n in H.items():
                v = [x for x in (fwd(k, i, n) for i in sel) if x is not None]
                out[f"{k}_{h}"] = round(st.mean(v), 1) if len(v) >= 20 else None
                out[f"{k}_{h}_win"] = round(sum(x > 0 for x in v) / len(v) * 100) if len(v) >= 20 else None
        # 세 자산(주식·금·비트) 6개월 동반 상승 비율
        v = [(fwd("spx", i, 126), fwd("gold", i, 126), fwd("btc", i, 126)) for i in sel]
        v = [x for x in v if None not in x]
        out["all3_up_6m"] = round(sum(all(y > 0 for y in x) for x in v) / len(v) * 100) if len(v) >= 20 else None
        return out

    allsel = list(range(len(days)))
    lv = lambda i: ry[days[i]]
    ch = lambda i, n=126: (ry[days[i]] - ry[days[i - n]]) if i >= n else None

    levels = [summ(allsel, "전체")]
    for lo, hi, lab in ((-9, 0, "0% 미만"), (0, 1, "0~1%"), (1, 2, "1~2%"), (2, 2.4, "2~2.4%"), (2.4, 9, "2.4% 이상")):
        levels.append(summ([i for i in allsel if lo <= lv(i) < hi], lab))
    chg = []
    for lo, hi, lab in ((-9, -0.5, "6개월 −0.5%p 이하"), (-0.5, 0, "−0.5~0"), (0, 0.5, "0~+0.5%p"), (0.5, 1, "+0.5~+1%p"), (1, 9, "+1%p 이상")):
        chg.append(summ([i for i in allsel if ch(i) is not None and lo <= ch(i) < hi], lab))

    # 2.4% 하향 돌파 이벤트: 직전 20거래일 모두 ≥2.4 이고 오늘 <2.4 (이후 60거래일 중복 제거)
    ev, last = [], -999
    for i in range(20, len(days)):
        if lv(i) < 2.4 and all(lv(j) >= 2.4 for j in range(i - 20, i)) and i - last > 60:
            r = {"date": days[i], "ry": lv(i)}
            for k in px:
                for h, n in H.items():
                    x = fwd(k, i, n); r[f"{k}_{h}"] = None if x is None else round(x, 1)
            ev.append(r); last = i
    # 2.4% 상향 돌파 이벤트
    up, last = [], -999
    for i in range(20, len(days)):
        if lv(i) >= 2.4 and all(lv(j) < 2.4 for j in range(i - 20, i)) and i - last > 60:
            r = {"date": days[i], "ry": lv(i)}
            for k in px:
                for h, n in H.items():
                    x = fwd(k, i, n); r[f"{k}_{h}"] = None if x is None else round(x, 1)
            up.append(r); last = i

    # 동행 상관: 주간(5거래일) 실질금리 변화 vs 같은 기간 수익
    def corr(a, b):
        ma, mb = st.mean(a), st.mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        return cov / (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    co = {}
    for k in px:
        for per, (s0, s1) in {"2003~2019": ("2003", "2020"), "2020~": ("2020", "2100")}.items():
            a, b = [], []
            for i in range(5, len(days), 5):
                if not (s0 <= days[i] < s1):
                    continue
                p0, p1 = px[k].get(days[i - 5]), px[k].get(days[i])
                if p0 and p1:
                    a.append(ry[days[i]] - ry[days[i - 5]]); b.append(p1 / p0 - 1)
            co[f"{k}_{per}"] = round(corr(a, b), 2) if len(a) > 30 else None
        # 주식·금 동행 상관 (실질금리가 공통 변수인지)
    # 명목 10년물과 실질금리 6개월 변화 상관
    a, b = [], []
    for i in range(126, len(days), 5):
        d0, d1 = days[i - 126], days[i]
        if d0 in nom and d1 in nom:
            a.append(ry[d1] - ry[d0]); b.append(nom[d1] - nom[d0])
    co["real_vs_nominal_6m_change"] = round(corr(a, b), 2)
    # 기존 규칙(명목 10년물 6개월 +1%p)과 실질 +1%p가 겹치는 날 비율
    n1 = [i for i in range(126, len(days)) if days[i] in nom and days[i - 126] in nom and nom[days[i]] - nom[days[i - 126]] >= 1]
    r1 = [i for i in range(126, len(days)) if ch(i) is not None and ch(i) >= 1]
    ov = len(set(n1) & set(r1))
    res = {"generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "from": days[0], "to": days[-1],
           "now": {"date": days[-1], "ry": lv(len(days) - 1), "chg6m": round(ch(len(days) - 1), 2),
                   "pctile": round(sum(ry[d] <= lv(len(days) - 1) for d in days) / len(days) * 100),
                   "max": max(ry.values()), "max_date": max(ry, key=ry.get)},
           "days_above_2_4": sum(lv(i) >= 2.4 for i in allsel),
           "levels": levels, "chg6m": chg, "cross_down_2_4": ev, "cross_up_2_4": up, "corr_weekly": co,
           "overlap": {"nominal_1pp_days": len(n1), "real_1pp_days": len(r1), "both": ov,
                       "nominal_rule": summ(n1, "명목 6개월 +1%p"), "real_rule": summ(r1, "실질 6개월 +1%p"),
                       "real_only": summ(sorted(set(r1) - set(n1)), "실질만 +1%p")}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
