"""사모대출(BDC)·CCC·신용 지표가 주식 하락장의 선행 신호였는지 검증 → data/credit_study.json
(11-18 Ben: Threads 'CCC 차환 부담 → 부도 증가, BDC 환매 > 유입' 글 검증)

- FRED: CCC 이하 OAS(BAMLH0A3HYC), BB OAS(BAMLH0A1HYBB), HY OAS(BAMLH0A0HYM2), BAA10Y,
        은행 C&I 대출 기준 강화 비율(DRTSCILM, 분기), 기업대출 연체율(DRBLACBS, 분기)
- Yahoo: ^GSPC(1990~), QQQ, ARCC(최대 BDC, 2004~), BIZD(BDC ETF, 2013~), HYG
- 신호마다 '처음 켜진 날'(120거래일 쿨다운) 뒤 S&P500 3/6/12개월 수익, 6개월 최대 추가 낙폭을
  무조건 평균과 비교. 하락장(고점 대비 −15% 이상)마다 −10% 도달일보다 먼저 켜졌는지(선행) 확인.
"""
import json, os, sys, bisect
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, yahoo  # noqa

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "credit_study.json")
COOL = 120


def closes(sym):
    rows = yahoo(sym, "max")
    return {r[0]: r[5] for r in rows}


def ffill(series, dates, lag_days=0):
    """[(date,v)] → dates에 맞춰 직전 값 (발표 지연 lag_days 반영)"""
    import datetime as dt
    s = []
    for d, v in series:
        if lag_days:
            d = (dt.date.fromisoformat(d) + dt.timedelta(days=lag_days)).isoformat()
        s.append((d, v))
    s.sort(); keys = [x[0] for x in s]
    out = []
    for d in dates:
        i = bisect.bisect_right(keys, d) - 1
        out.append(s[i][1] if i >= 0 else None)
    return out


def main():
    spx = closes("^GSPC")
    dates = sorted(d for d in spx if d >= "1990-01-01")
    px = [spx[d] for d in dates]
    n = len(dates)
    res = {"generated": dates[-1], "series_start": {}, "signals": [], "events": [], "overlap": {}}

    F = {}
    for k, sid, lag in [("ccc", "BAMLH0A3HYC", 1), ("bb", "BAMLH0A1HYBB", 1), ("hy", "BAMLH0A0HYM2", 1),
                        ("baa", "BAA10Y", 1), ("sloos", "DRTSCILM", 120), ("delinq", "DRBLACBS", 150)]:
        try:
            raw = fred(sid, "1986-01-01")
        except Exception as e:  # noqa
            print("fred fail", sid, e); raw = []
        res["series_start"][sid] = raw[0][0] if raw else None
        print(sid, len(raw), raw[0] if raw else None, raw[-1] if raw else None)
        F[k] = ffill(raw, dates, lag) if raw else [None] * n
        F[k + "_start"] = (raw[0][0] if raw else "9999")
    P = {}
    for sym in ["QQQ", "ARCC", "BIZD", "HYG"]:
        try:
            c = closes(sym)
        except Exception as e:  # noqa
            print("yahoo fail", sym, e); c = {}
        res["series_start"][sym] = min(c) if c else None
        P[sym] = [c.get(d) for d in dates]
        # 휴장 차이 보정
        last = None
        for i in range(n):
            if P[sym][i] is None and last is not None and dates[i] >= min(c or {"9": 0}):
                P[sym][i] = last
            last = P[sym][i] if P[sym][i] is not None else last
        print(sym, res["series_start"][sym])

    # HY: FRED 시작 전은 BAA10Y×2.3−1.0 근사 (backtest_portfolio.py와 같은 식)
    hy = [F["hy"][i] if dates[i] >= F["hy_start"] else (2.3 * F["baa"][i] - 1.0 if F["baa"][i] is not None else None) for i in range(n)]

    def dd1y(a, i):
        w = [x for x in a[max(0, i - 252):i + 1] if x is not None]
        return a[i] / max(w) - 1 if a[i] is not None and len(w) > 200 else None

    def chg(a, i, k):
        return a[i] - a[i - k] if i >= k and a[i] is not None and a[i - k] is not None else None

    def ret(a, i, k):
        return a[i] / a[i - k] - 1 if i >= k and a[i] is not None and a[i - k] is not None and a[i - k] > 0 else None

    defs = {
        "HY ≥ 5% (현재 신호등 빨강)": lambda i: hy[i] is not None and hy[i] >= 5,
        "HY ≥ 6% (위기)": lambda i: hy[i] is not None and hy[i] >= 6,
        "HY 3개월 +1.5%p↑": lambda i: (chg(hy, i, 63) or 0) >= 1.5,
        "CCC ≥ 12%": lambda i: F["ccc"][i] is not None and F["ccc"][i] >= 12,
        "CCC 3개월 +3%p↑": lambda i: F["ccc"][i] is not None and (chg(F["ccc"], i, 63) or 0) >= 3,
        "CCC−BB 차이 3개월 +2%p↑": lambda i: None not in (F["ccc"][i], F["bb"][i]) and i >= 63 and None not in (F["ccc"][i - 63], F["bb"][i - 63])
                                           and (F["ccc"][i] - F["bb"][i]) - (F["ccc"][i - 63] - F["bb"][i - 63]) >= 2,
        "ARCC 1년 고점 −15%↓": lambda i: (dd1y(P["ARCC"], i) or 0) <= -0.15,
        "ARCC 1년 고점 −20%↓": lambda i: (dd1y(P["ARCC"], i) or 0) <= -0.20,
        "ARCC 3개월 S&P 대비 −10%p↓": lambda i: (lambda a, b: a is not None and b is not None and a - b <= -0.10)(ret(P["ARCC"], i, 63), ret(px, i, 63)),
        "BIZD 1년 고점 −15%↓": lambda i: (dd1y(P["BIZD"], i) or 0) <= -0.15,
        "HYG 1년 고점 −8%↓": lambda i: (dd1y(P["HYG"], i) or 0) <= -0.08,
        "은행 대출 기준 강화 ≥ 20%": lambda i: F["sloos"][i] is not None and F["sloos"][i] >= 20,
        "기업대출 연체율 1년 +0.5%p↑": lambda i: (chg(F["delinq"], i, 252) or 0) >= 0.5,
    }

    fwd = lambda i, k: px[i + k] / px[i] - 1 if i + k < n else None
    def mdd6(i):
        if i + 126 >= n:
            return None
        return min(px[i:i + 127]) / px[i] - 1
    hz = {"3m": 63, "6m": 126, "12m": 252}

    # 기준선: 같은 기간 모든 날
    def base(start_i):
        b = {}
        for k, h in hz.items():
            v = [fwd(i, h) for i in range(start_i, n - h)]
            b[k] = round(sum(v) / len(v) * 100, 1) if v else None
        m = [mdd6(i) for i in range(start_i, n - 126)]
        b["mdd6"] = round(sum(m) / len(m) * 100, 1) if m else None
        b["p10"] = round(sum(1 for x in m if x <= -0.10) / len(m) * 100, 0) if m else None
        return b

    # 하락장: S&P 고점 대비 −15% 이상 하락 구간
    events = []
    peak_i = 0; i = 0
    while i < n:
        if px[i] >= px[peak_i]:
            peak_i = i
        elif px[i] / px[peak_i] - 1 <= -0.15:
            j = i; trough = i
            while j < n and px[j] < px[peak_i]:
                if px[j] < px[trough]:
                    trough = j
                j += 1
            hit10 = next(k for k in range(peak_i, n) if px[k] / px[peak_i] - 1 <= -0.10)
            events.append({"peak": dates[peak_i], "hit10": dates[hit10], "trough": dates[trough],
                           "mdd": round((px[trough] / px[peak_i] - 1) * 100, 1), "pi": peak_i, "hi": hit10, "ti": trough})
            i = j; peak_i = min(j, n - 1)
            continue
        i += 1
    print("events", [(e["peak"], e["mdd"]) for e in events])

    on_days = {}
    for name, f in defs.items():
        on = [bool(f(i)) for i in range(n)]
        on_days[name] = on
        first = [i for i in range(n) if on[i]]
        if not first:
            res["signals"].append({"name": name, "n": 0}); continue
        start_i = first[0]
        # 데이터가 있는 첫날 (판정 가능일)
        trig = []; last = -10**9
        for i in range(1, n):
            if on[i] and not on[i - 1] and i - last >= COOL:
                trig.append(i); last = i
        rows = []
        for i in trig:
            rows.append({"d": dates[i], **{k: (round(fwd(i, h) * 100, 1) if fwd(i, h) is not None else None) for k, h in hz.items()},
                         "mdd6": round(mdd6(i) * 100, 1) if mdd6(i) is not None else None})
        def avg(k):
            v = [r[k] for r in rows if r[k] is not None]
            return round(sum(v) / len(v), 1) if v else None
        m6 = [r["mdd6"] for r in rows if r["mdd6"] is not None]
        # 하락장별 선행: 고점 1년 전 ~ −10% 도달일 사이 켜짐 = 선행, −10% 뒤 바닥 전 = 늦음, 없음 = 놓침
        ev = []
        for e in events:
            lo = max(0, e["pi"] - 252)
            first_on = next((k for k in range(lo, e["ti"] + 1) if on[k]), None)
            if first_on is None:
                st = "놓침"
            elif first_on <= e["hi"]:
                st = "선행"
            else:
                st = "늦음"
            ev.append({"peak": e["peak"], "st": st, "on": dates[first_on] if first_on is not None else None})
        res["signals"].append({
            "name": name, "n": len(trig),
            "first_on": dates[start_i],
            "avg": {k: avg(k) for k in ["3m", "6m", "12m", "mdd6"]},
            "p10": round(sum(1 for x in m6 if x <= -10) / len(m6) * 100, 0) if m6 else None,
            "events": ev, "trig": rows,
            "on_share": round(sum(on) / n * 100, 1)})

    # 자료 시작일 표시 (신호별)
    srcmap = {"CCC": "BAMLH0A3HYC", "ARCC": "ARCC", "BIZD": "BIZD", "HYG": "HYG", "은행": "DRTSCILM", "기업대출": "DRBLACBS"}
    for s in res["signals"]:
        for k, v in srcmap.items():
            if s["name"].startswith(k):
                s["src_start"] = res["series_start"].get(v)
                if s.get("events") and s["src_start"]:
                    for e in s["events"]:
                        if e["peak"] < s["src_start"]:
                            e["st"] = "자료 없음"
        if s["name"].startswith("HY") and s.get("events"):
            s["src_start"] = "BAA10Y 근사 ~" + str(F["hy_start"])

    # 중복: CCC·ARCC 신호가 켜진 날 중 HY ≥ 5도 켜진 비율, HY 신호 없이 단독으로 켜진 날 뒤 성과
    hy5 = on_days["HY ≥ 5% (현재 신호등 빨강)"]
    for name in defs:
        if name.startswith("HY"):
            continue
        on = on_days[name]
        both = sum(1 for i in range(n) if on[i] and hy5[i]); tot = sum(on)
        solo = [i for i in range(n - 126) if on[i] and not hy5[i]]
        res["overlap"][name] = {"days": tot, "with_hy5_pct": round(both / tot * 100, 0) if tot else None,
                                 "solo_days": len(solo),
                                 "solo_6m": round(sum(fwd(i, 126) for i in solo) / len(solo) * 100, 1) if solo else None,
                                 "solo_mdd6": round(sum(mdd6(i) for i in solo) / len(solo) * 100, 1) if solo else None}

    res["events"] = [{k: e[k] for k in ["peak", "hit10", "trough", "mdd"]} for e in events]
    res["base_all"] = base(0)
    # 최근 값
    res["now"] = {"date": dates[-1], "ccc": F["ccc"][-1], "bb": F["bb"][-1], "hy": hy[-1],
                  "ccc_3m": chg(F["ccc"], n - 1, 63), "sloos": F["sloos"][-1], "delinq": F["delinq"][-1],
                  "arcc_dd1y": dd1y(P["ARCC"], n - 1), "bizd_dd1y": dd1y(P["BIZD"], n - 1), "hyg_dd1y": dd1y(P["HYG"], n - 1)}
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    for s in res["signals"]:
        print(s["name"], s.get("n"), s.get("avg"), s.get("p10"), [(e["peak"], e["st"]) for e in s.get("events", [])])
    print(json.dumps(res["overlap"], ensure_ascii=False))
    print(res["now"])


if __name__ == "__main__":
    main()
