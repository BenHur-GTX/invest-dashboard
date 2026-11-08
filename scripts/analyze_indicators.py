#!/usr/bin/env python3
"""매수 타이밍 보조지표 검증 → data/indicator_study.json
기존 기준(RSI·200일선·이격도·VIX·공포탐욕)에 슬로우 스토캐스틱·볼린저 밴드를 더하면 나아지는지 확인.

1) 신호 이후 수익률(5·21·63거래일)·승률을 전체 평균과 비교. 전 기간 / 하락 국면(5년 고점 대비 -10% 이하) 따로.
2) 분할매수 회차 실험: 5년 고점 대비 -10/-15/-20/-25/-30% 첫 도달일(그 자리 매수)과
   '도달 후 지표 신호가 뜰 때까지 기다렸다 매수(최대 20거래일)'의 매수가 차이.
GitHub Actions 수동 실행(workflow_dispatch)."""
import json, os, statistics as st, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as B

TICKERS = [("QQQ", "나스닥100"), ("SPY", "S&P500"), ("SOXX", "반도체"), ("^KS11", "코스피")]
H = [5, 21, 63]
DD_WIN = 1260
TRANCHES = [-10, -15, -20, -25, -30]
WAIT = 20


def stoch_slow(h, l, c, n=14, k=3, d=3):
    fast = [None] * len(c)
    for i in range(n - 1, len(c)):
        hh, ll = max(h[i - n + 1:i + 1]), min(l[i - n + 1:i + 1])
        fast[i] = (c[i] - ll) / (hh - ll) * 100 if hh > ll else 50
    def ma(a, m):
        out = [None] * len(a)
        for i in range(len(a)):
            w = a[max(0, i - m + 1):i + 1]
            if len(w) == m and all(x is not None for x in w):
                out[i] = sum(w) / m
        return out
    K = ma(fast, k)
    D = ma(K, d)
    return K, D


def boll(c, n=20, m=2.0):
    lo, mid, up = [None] * len(c), [None] * len(c), [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]; mu = sum(w) / n; sd = st.pstdev(w)
        lo[i], mid[i], up[i] = mu - m * sd, mu, mu + m * sd
    return lo, mid, up


def prep(sym):
    rows = B.yahoo(sym, "max")
    d = [r[0] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    rsi = B.rsi_series(c)
    K, D = stoch_slow(h, l, c)
    lo, mid, up = boll(c)
    ma20 = [B.sma(c, 20, i) for i in range(len(c))]
    dd5 = []
    for i in range(len(c)):
        pk = max(c[max(0, i - DD_WIN + 1):i + 1]); dd5.append((c[i] / pk - 1) * 100)
    return dict(d=d, c=c, rsi=rsi, K=K, D=D, lo=lo, mid=mid, up=up, ma20=ma20, dd5=dd5)


def sig_funcs(X):
    c, K, D, lo, rsi, ma20 = X["c"], X["K"], X["D"], X["lo"], X["rsi"], X["ma20"]
    def ok(*a): return all(v is not None for v in a)
    return {
        "RSI ≤ 30 (기존)": lambda i: ok(rsi[i]) and rsi[i] <= 30,
        "RSI ≤ 25 (심플)": lambda i: ok(rsi[i]) and rsi[i] <= 25,
        "스토캐스틱 %K ≤ 20": lambda i: ok(K[i]) and K[i] <= 20,
        "스토캐스틱 20 아래 골든크로스": lambda i: i > 0 and ok(K[i], D[i], K[i-1], D[i-1]) and K[i-1] <= D[i-1] and K[i] > D[i] and min(K[i-1], D[i-1]) <= 20,
        "볼린저 하단 이탈": lambda i: ok(lo[i]) and c[i] < lo[i],
        "볼린저 하단 재진입": lambda i: i > 0 and ok(lo[i], lo[i-1]) and c[i-1] < lo[i-1] and c[i] >= lo[i],
        "20일 이격도 ≤ 92": lambda i: ok(ma20[i]) and c[i] / ma20[i] * 100 <= 92,
        "RSI ≤ 30 + 스토캐스틱 골든크로스(5일 내)": lambda i: i >= 5 and ok(rsi[i]) and min(r for r in rsi[i-5:i+1] if r is not None) <= 30 and ok(K[i], D[i], K[i-1], D[i-1]) and K[i-1] <= D[i-1] and K[i] > D[i],
    }


def fwd_stats(X, idxs, cooldown=5):
    c = X["c"]; n = len(c)
    # 연속 신호는 cooldown 거래일 간격으로 묶음
    ev, last = [], -10**9
    for i in idxs:
        if i - last >= cooldown:
            ev.append(i); last = i
    out = {"n": len(ev)}
    for h in H:
        r = [(c[i + h] / c[i] - 1) * 100 for i in ev if i + h < n]
        out[f"r{h}"] = round(st.mean(r), 2) if r else None
        out[f"w{h}"] = round(sum(x > 0 for x in r) / len(r) * 100, 0) if r else None
    return out


def study_signals(X):
    n = len(X["c"]); start = 260
    sf = sig_funcs(X)
    res = {}
    for scope, cond in [("전체", lambda i: True), ("하락 국면(5년 고점 -10% 이하)", lambda i: X["dd5"][i] <= -10)]:
        base_idx = [i for i in range(start, n) if cond(i)]
        rows = {"기준(아무 날)": fwd_stats(X, base_idx, cooldown=1)}
        for name, f in sf.items():
            rows[name] = fwd_stats(X, [i for i in base_idx if f(i)])
        res[scope] = rows
    return res


def study_tranches(X):
    """회차 도달일 즉시 매수 vs 신호 대기 매수의 가격 차이(+면 대기가 더 싸게 삼)."""
    c, dd = X["c"], X["dd5"]; n = len(c)
    sf = sig_funcs(X)
    waits = {k: sf[k] for k in ["RSI ≤ 30 (기존)", "스토캐스틱 20 아래 골든크로스", "볼린저 하단 재진입", "RSI ≤ 30 + 스토캐스틱 골든크로스(5일 내)"]}
    events = []
    armed = {t: True for t in TRANCHES}
    for i in range(260, n):
        if dd[i] >= -1:
            armed = {t: True for t in TRANCHES}
        for t in TRANCHES:
            if armed[t] and dd[i] <= t:
                armed[t] = False; events.append((t, i))
    out = {}
    for name, f in waits.items():
        diffs, missed, days = [], 0, []
        for t, i in events:
            j = next((k for k in range(i, min(n, i + WAIT + 1)) if f(k)), None)
            if j is None:
                j = min(n - 1, i + WAIT); missed += 1
            diffs.append((c[i] / c[j] - 1) * 100); days.append(j - i)
        out[name] = {
            "events": len(events),
            "avg_saving_pct": round(st.mean(diffs), 2) if diffs else None,
            "median_saving_pct": round(st.median(diffs), 2) if diffs else None,
            "better_pct": round(sum(x > 0 for x in diffs) / len(diffs) * 100, 0) if diffs else None,
            "worst_pct": round(min(diffs), 2) if diffs else None,
            "no_signal_in_20d": missed,
            "avg_wait_days": round(st.mean(days), 1) if days else None,
        }
    return out


def main():
    out = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "tickers": {}}
    for sym, name in TICKERS:
        try:
            X = prep(sym); time.sleep(0.5)
            out["tickers"][sym] = {"name": name, "start": X["d"][0], "end": X["d"][-1],
                                   "signals": study_signals(X), "tranches": study_tranches(X)}
            print(sym, "ok", X["d"][0], X["d"][-1])
        except Exception as e:  # noqa
            out["tickers"][sym] = {"name": name, "error": str(e)}
            print(sym, "fail", e)
    os.makedirs("data", exist_ok=True)
    with open("data/indicator_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
