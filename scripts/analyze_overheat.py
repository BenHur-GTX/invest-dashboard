#!/usr/bin/env python3
"""과열 매도 신호 검증 → data/overheat_study.json
1) 신호 발생일 이후 QQQ·QLD 수익률(1·3·6·12개월)과 이후 3개월 최대 낙폭을 전체 평균과 비교
2) '신호 시 QLD 일부 매도 → 현금 → 낙폭 -10%에서 재매수' 규칙을 보유와 비교
GitHub Actions에서 수동 실행(workflow_dispatch)."""
import json, os, statistics as st, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as B

H = [21, 63, 126, 252]


def prep():
    q = B.yahoo("QQQ", "max"); time.sleep(0.5)
    l = B.yahoo("QLD", "max"); time.sleep(0.5)
    v = B.yahoo("^VIX", "max"); time.sleep(0.5)
    irx = B.yahoo("^IRX", "max")
    vix = {r[0]: r[4] for r in v}
    rate = {r[0]: r[4] for r in irx}
    dates = [r[0] for r in q]; c = [r[4] for r in q]; adj = [r[5] for r in q]
    rsi = B.rsi_series(c)
    # 주봉 RSI·50주선: 주 마지막 거래일에 계산, 그 주 다른 날엔 직전 주 값
    from datetime import datetime
    wk_idx, wk_close = [], []
    for i, d in enumerate(dates):
        y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        if wk_idx and wk_idx[-1][0] == (y, w):
            wk_idx[-1] = ((y, w), i); wk_close[-1] = c[i]
        else:
            wk_idx.append(((y, w), i)); wk_close.append(c[i])
    wrsi = B.rsi_series(wk_close)
    wma50 = [B.sma(wk_close, 50, k) for k in range(len(wk_close))]
    wrsi_d, gap50w_d = [None] * len(c), [None] * len(c)
    k = 0
    for j, (_, i_end) in enumerate(wk_idx):
        start = wk_idx[j - 1][1] + 1 if j else 0
        for i in range(start, i_end + 1):
            wrsi_d[i] = wrsi[j - 1] if j else None
            gap50w_d[i] = (c[i] / wma50[j - 1] * 100) if j and wma50[j - 1] else None
    ma200 = [B.sma(c, 200, i) for i in range(len(c))]
    ma50 = [B.sma(c, 50, i) for i in range(len(c))]
    rows = []
    peak = 0
    for i in range(len(c)):
        peak = max(peak, c[i])
        rows.append({
            "d": dates[i], "c": c[i], "adj": adj[i], "rsi": rsi[i], "wrsi": wrsi_d[i], "gap50w": gap50w_d[i],
            "vs200": (c[i] / ma200[i] - 1) * 100 if ma200[i] else None,
            "vs50": (c[i] / ma50[i] - 1) * 100 if ma50[i] else None,
            "vix": vix.get(dates[i]), "dd": (c[i] / peak - 1) * 100, "rf": rate.get(dates[i]),
        })
    qld = {r[0]: r[5] for r in l}
    return rows, qld


SIGNALS = {
    "RSI ≥ 70": lambda r: r["rsi"] is not None and r["rsi"] >= 70,
    "RSI ≥ 75": lambda r: r["rsi"] is not None and r["rsi"] >= 75,
    "RSI ≥ 80": lambda r: r["rsi"] is not None and r["rsi"] >= 80,
    "주봉 RSI ≥ 70": lambda r: r["wrsi"] is not None and r["wrsi"] >= 70,
    "주봉 RSI ≥ 75": lambda r: r["wrsi"] is not None and r["wrsi"] >= 75,
    "200일선 +10%": lambda r: r["vs200"] is not None and r["vs200"] >= 10,
    "200일선 +15%": lambda r: r["vs200"] is not None and r["vs200"] >= 15,
    "200일선 +20%": lambda r: r["vs200"] is not None and r["vs200"] >= 20,
    "50일선 +8%": lambda r: r["vs50"] is not None and r["vs50"] >= 8,
    "50주선 이격 115%": lambda r: r["gap50w"] is not None and r["gap50w"] >= 115,
    "50주선 이격 120%": lambda r: r["gap50w"] is not None and r["gap50w"] >= 120,
    "VIX ≤ 13": lambda r: r["vix"] is not None and r["vix"] <= 13,
}


def combo(n, keys):
    return lambda r: sum(1 for k in keys if SIGNALS[k](r)) >= n


CORE = ["RSI ≥ 75", "주봉 RSI ≥ 70", "200일선 +15%", "50일선 +8%", "VIX ≤ 13"]
for n in (2, 3, 4):
    SIGNALS[f"핵심 5개 중 {n}개+"] = combo(n, CORE)


def events(rows, f, start_i, cool=21):
    ev, last = [], -10 ** 9
    for i in range(start_i, len(rows)):
        if f(rows[i]) and i - last > cool:
            ev.append(i)
        if f(rows[i]):
            last = i
    return ev


def fwd(rows, qld, idxs):
    out = {}
    for h in H:
        rq, rl = [], []
        for i in idxs:
            if i + h < len(rows):
                rq.append((rows[i + h]["adj"] / rows[i]["adj"] - 1) * 100)
                d0, d1 = rows[i]["d"], rows[i + h]["d"]
                if d0 in qld and d1 in qld:
                    rl.append((qld[d1] / qld[d0] - 1) * 100)
        out[h] = {
            "n": len(rq),
            "qqq_mean": round(st.mean(rq), 2) if rq else None,
            "qqq_med": round(st.median(rq), 2) if rq else None,
            "qqq_neg": round(sum(1 for x in rq if x < 0) / len(rq) * 100) if rq else None,
            "qld_mean": round(st.mean(rl), 2) if rl else None,
            "qld_med": round(st.median(rl), 2) if rl else None,
        }
    # 이후 63일 내 최대 낙폭 (QQQ)
    dds = []
    for i in idxs:
        seg = [rows[k]["c"] for k in range(i, min(i + 64, len(rows)))]
        if len(seg) > 10:
            dds.append((min(seg) / seg[0] - 1) * 100)
    out["dd63_med"] = round(st.median(dds), 1) if dds else None
    out["dd63_le10"] = round(sum(1 for x in dds if x <= -10) / len(dds) * 100) if dds else None
    return out


def strat(rows, qld, sig, sell_pct, rebuy_dd=-10, max_wait=252, cool=126, start="2006-06-21"):
    """QLD 보유. 신호일 QLD sell_pct% 매도 → 현금(T-bill 이자). QQQ 고점 대비 rebuy_dd% 도달 또는 max_wait일 경과 시 현금 전액 재매수.
    매도 후 cool일 동안 추가 매도 없음(연 2회 수준)."""
    idx = [i for i, r in enumerate(rows) if r["d"] >= start and r["d"] in qld]
    sh, cash, last_sell, wait = 1.0 / qld[rows[idx[0]]["d"]], 0.0, -10 ** 9, 0
    sells, curve = 0, []
    for k, i in enumerate(idx):
        r = rows[i]; p = qld[r["d"]]
        if cash > 0:
            cash *= 1 + (r["rf"] or 0) / 100 / 252
            wait += 1
            if r["dd"] <= rebuy_dd or wait >= max_wait:
                sh += cash / p; cash = 0; wait = 0
        if sig(r) and i - last_sell >= cool and sh > 0:
            s = sh * sell_pct / 100
            cash += s * p; sh -= s; last_sell = i; sells += 1; wait = 0
        curve.append(sh * p + cash)
    dts = [rows[i]["d"] for i in idx]
    base = [qld[d] / qld[dts[0]] for d in dts]
    return {"rule": B.stats(curve, dts), "hold": B.stats(base, dts), "sells": sells}


def main():
    rows, qld = prep()
    start_i = 260
    base = fwd(rows, qld, list(range(start_i, len(rows))))
    res = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "period": [rows[start_i]["d"], rows[-1]["d"]],
           "baseline": base, "signals": {}, "strategies": []}
    for name, f in SIGNALS.items():
        ev = events(rows, f, start_i)
        res["signals"][name] = {"events": len(ev), "recent": [rows[i]["d"] for i in ev[-5:]], **fwd(rows, qld, ev)}
    for name in ["RSI ≥ 75", "RSI ≥ 80", "200일선 +15%", "200일선 +20%", "50주선 이격 120%", "핵심 5개 중 2개+", "핵심 5개 중 3개+", "핵심 5개 중 4개+"]:
        for pct in (10, 20, 30):
            for rb in (-10, -15):
                r = strat(rows, qld, SIGNALS[name], pct, rebuy_dd=rb)
                res["strategies"].append({"signal": name, "sell_pct": pct, "rebuy_dd": rb, **r})
    # 현재 값
    r = rows[-1]
    res["now"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}
    res["now_signals"] = [k for k, f in SIGNALS.items() if f(r)]
    out = os.path.join(B.DATA, "overheat_study.json")
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ok", len(rows))


if __name__ == "__main__":
    main()
