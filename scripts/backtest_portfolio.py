#!/usr/bin/env python3
"""5개 계좌 통합 백테스트 → data/portfolio_bt.json
현재 대시보드 규칙(2026-11-08)을 과거 4개 위기 시작점(QQQ 직전 고점)에 그대로 적용.
시작 잔고 = 현재 잔고(IRP 6138만, 연금저축 377만, 스윙 700만, 장투·현금 0), 월 적립 장투 200만·현금 85만·연금저축 45만.
모든 평가는 원화(DEXKOUS 환율). 세금·수수료·환전 스프레드 제외. GitHub Actions 수동 실행."""
import json, os, sys, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as B

MAN = 1e4
INIT = {"irp": 6138 * MAN, "pension": 377 * MAN, "swing": 700 * MAN}
MONTHLY = {"longterm": 200 * MAN, "ammo": 85 * MAN, "pension": 45 * MAN}
SCEN = [
    ("닷컴버블", "1999-12-01", "2000-12-31"),
    ("금융위기", "2007-06-01", "2008-06-30"),
    ("코로나", "2019-12-01", "2020-03-01"),
    ("2022 금리인상·러우전쟁", "2021-09-01", "2022-01-31"),
]
MONTHLY_RULES = [  # (min dd 초과, QQQM, SPYM, QLD, TQQQ) 만원 / 200만
    (-10, 80, 60, 40, 0), (-15, 90, 60, 50, 0), (-20, 90, 50, 60, 0), (-30, 60, 20, 120, 0), (-999, 40, 0, 120, 40)]
AMMO_T = [(-30, 15, {"QQQ": 70, "QLD": 30}), (-40, 23.5, {"QQQ": 60, "QLD": 40}),
          (-60, 38.5, {"QLD": 80, "QQQ": 20}), (-80, 100, {"QLD": 80, "TQQQ": 20})]
LT_POOL_T = [(-10, 10, {"QQQ": 70, "QLD": 30}), (-15, 22.2, {"QQQ": 60, "QLD": 40}),
             (-20, 42.9, {"QLD": 80, "QQQ": 20}), (-30, 100, {"QLD": 80, "TQQQ": 20})]
DD_WIN = int(os.environ.get("DD_WIN", "1260"))
IRP_T = {1: (55, 60), 2: (58, 62), 3: (62, 65), 4: (68, 70), 5: (55, 60)}


def ff(series, dates):
    """[(d,v)] → dates 기준 직전값 채움"""
    s = sorted(series); out = []; j = 0; cur = None
    for d in dates:
        while j < len(s) and s[j][0] <= d:
            cur = s[j][1]; j += 1
        out.append(cur)
    return out


def splice(dates, base_ret, real, k=1.0, cost=None):
    """real 데이터가 있으면 그 수익률, 없으면 base_ret × k − 비용으로 합성한 지수"""
    real = dict(real) if real else {}
    idx = [100.0]
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        if d0 in real and d1 in real:
            r = real[d1] / real[d0] - 1
        else:
            r = k * base_ret[i] - (cost[i] if cost else 0)
        idx.append(idx[-1] * (1 + r))
    return idx


def load():
    y = {}
    for s in ["QQQ", "SPY", "QLD", "TQQQ", "SCHD", "SOXX", "^SOX", "^VIX", "^IRX"]:
        try:
            y[s] = B.yahoo(s, "max"); print("yahoo", s, len(y[s]), flush=True)
        except Exception as e:
            print("yahoo fail", s, e, flush=True); y[s] = []
        time.sleep(0.4)
    f = {}
    for k, sid in {"fx": "DEXKOUS", "ft_old": "DFEDTAR", "ft_new": "DFEDTARU", "dgs2": "DGS2", "sahm": "SAHMREALTIME",
                   "icsa": "ICSA", "walcl": "WALCL", "tga": "WTREGEN", "rrp": "RRPONTSYD", "hy": "BAMLH0A0HYM2", "baa": "BAA10Y"}.items():
        try:
            f[k] = B.fred(sid, "1990-01-01"); print("fred", sid, len(f[k]), flush=True)
        except Exception as e:
            print("fred fail", sid, e, flush=True); f[k] = []
        time.sleep(0.3)
    return y, f


def prep(y, f):
    q = y["QQQ"]; dates = [r[0] for r in q]; c = [r[4] for r in q]; adj = [r[5] for r in q]
    n = len(dates)
    rf = ff([(r[0], r[4]) for r in y["^IRX"]], dates); rf = [(x or 0) / 100 for x in rf]
    qret = [0] + [adj[i] / adj[i - 1] - 1 for i in range(1, n)]
    spy_adj = dict((r[0], r[5]) for r in y["SPY"])
    spy = ff(list(spy_adj.items()), dates)
    sret = [0] + [spy[i] / spy[i - 1] - 1 for i in range(1, n)]
    sox = dict((r[0], r[4]) for r in y["^SOX"])
    soxv = ff(list(sox.items()), dates)
    soxret = [0] + [(soxv[i] / soxv[i - 1] - 1) if soxv[i - 1] else 0 for i in range(1, n)]
    P = {
        "QQQ": [a / adj[0] * 100 for a in adj],
        "SPY": [s / spy[0] * 100 for s in spy],
        "QLD": splice(dates, qret, [(r[0], r[5]) for r in y["QLD"]], 2, [(0.0095 + rf[i]) / 252 for i in range(n)]),
        "TQQQ": splice(dates, qret, [(r[0], r[5]) for r in y["TQQQ"]], 3, [(0.0095 + 2 * rf[i]) / 252 for i in range(n)]),
        "SCHD": splice(dates, sret, [(r[0], r[5]) for r in y["SCHD"]]),
        "SOXX": splice(dates, soxret, [(r[0], r[5]) for r in y["SOXX"]]),
    }
    sg = [100.0]
    for i in range(1, n):
        sg.append(sg[-1] * (1 + rf[i - 1] / 252))
    P["SGOV"] = sg
    fx = ff(f["fx"], dates)
    first_fx = next(v for v in fx if v)
    fx = [v or first_fx for v in fx]
    # 지표 (QQQ 종가)
    rsi = B.rsi_series(c)
    ma200 = [B.sma(c, 200, i) for i in range(n)]
    ma60 = [B.sma(c, 60, i) for i in range(n)]
    wk, wc = [], []
    for i, d in enumerate(dates):
        yy, ww, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        if wk and wk[-1][0] == (yy, ww):
            wk[-1] = ((yy, ww), i); wc[-1] = c[i]
        else:
            wk.append(((yy, ww), i)); wc.append(c[i])
    wrsi = B.rsi_series(wc); wma = [B.sma(wc, 50, k) for k in range(len(wc))]
    wrsi_d, gap_d = [None] * n, [None] * n
    for j, (_, ie) in enumerate(wk):
        st = wk[j - 1][1] + 1 if j else 0
        for i in range(st, ie + 1):
            wrsi_d[i] = wrsi[j - 1] if j else None
            gap_d[i] = c[i] / wma[j - 1] * 100 if j and wma[j - 1] else None
    vix_map = {r[0]: r[4] for r in y["^VIX"]}
    vix = ff(list(vix_map.items()), dates)
    states = B.qqq_state_series(q, vix_map)
    # 낙폭 기준 고점: 최근 5년(1260거래일) 최고가. 사상 최고가 기준이면 2000년 고점 때문에 2007~2015년 내내 '-50% 이하 폭락'으로 판정됨
    from collections import deque
    dq, dd = deque(), []
    for k, x in enumerate(c):
        while dq and c[dq[-1]] <= x: dq.pop()
        dq.append(k)
        while dq[0] <= k - DD_WIN: dq.popleft()
        dd.append((x / c[dq[0]] - 1) * 100)
    # SOXX 지표
    sx = P["SOXX"]; srsi = B.rsi_series(sx)
    sdd52 = [(sx[i] / max(sx[max(0, i - 251):i + 1]) - 1) * 100 for i in range(n)]
    # 거시
    ft = sorted(f["ft_old"] + f["ft_new"])
    ft_d = ff(ft, dates)
    changes = [(ft[i][0], ft[i][1] - ft[i - 1][1]) for i in range(1, len(ft)) if abs(ft[i][1] - ft[i - 1][1]) > 1e-9]
    dgs2 = ff(f["dgs2"], dates); sahm = ff(f["sahm"], dates)
    ic = f["icsa"]; ic4 = [(ic[i][0], sum(x[1] for x in ic[max(0, i - 3):i + 1]) / min(4, i + 1)) for i in range(len(ic))]
    ic4 = ff(ic4, dates)
    hy_full = f["hy"]
    hy_start = hy_full[0][0] if hy_full else "9999"
    hy = ff(hy_full, dates)
    baa = ff(f["baa"], dates)
    # 순유동성 (주간)
    tga = dict(f["tga"]); rrp = sorted(f["rrp"]); nl = []
    j = 0; rcur = 0
    for d, w in f["walcl"]:
        while j < len(rrp) and rrp[j][0] <= d:
            rcur = rrp[j][1]; j += 1
        if d in tga:
            nl.append((d, w / 1000 - tga[d] / 1000 - rcur))
    nl_info = []
    down = 0
    for i in range(len(nl)):
        down = down + 1 if i and nl[i][1] < nl[i - 1][1] else 0
        chg4 = nl[i][1] - nl[i - 4][1] if i >= 4 else None
        nl_info.append((nl[i][0], (down, chg4)))
    nl_d = ff(nl_info, dates)
    return dict(dates=dates, c=c, P=P, fx=fx, rf=rf, rsi=rsi, wrsi=wrsi_d, gap50w=gap_d, ma200=ma200, ma60=ma60, vix=vix,
                states=states, dd=dd, srsi=srsi, sdd52=sdd52, ft=ft_d, changes=changes, dgs2=dgs2, sahm=sahm, ic4=ic4,
                hy=hy, hy_start=hy_start, baa=baa, nl=nl_d)


def macro(D, i):
    d = D["dates"][i]
    six = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=182)).strftime("%Y-%m-%d")
    rec = [x for x in D["changes"] if six <= x[0] <= d]
    s, ic = D["sahm"][i], D["ic4"][i]
    emp = "r" if (s is not None and s >= 0.5) or (ic is not None and ic >= 300000) else "y" if (s is not None and s >= 0.3) or (ic is not None and ic >= 250000) else "g"
    hikes = sum(1 for x in rec if x[1] > 0); cuts = sum(1 for x in rec if x[1] < 0); emerg = any(x[1] <= -0.5 for x in rec)
    if emerg: rate = "r"
    elif hikes: rate = "y"
    elif cuts: rate = "r" if emp == "r" else "g"
    else:
        past = [x for x in D["changes"] if x[0] <= d]
        lastup = past and past[-1][1] > 0
        rate = "y" if lastup and D["dgs2"][i] is not None and D["ft"][i] is not None and D["dgs2"][i] < D["ft"][i] else "g"
    nl = D["nl"][i]
    if nl is None: liq = "n"
    else:
        down, chg4 = nl
        liq = "r" if down >= 13 else "y" if (chg4 is not None and chg4 < 0) else "g"
    # HY: FRED가 최근 몇 년만 주면 그 이전은 BAA10Y로 근사(hy ≈ 2.3×baa − 1.0)
    hy = D["hy"][i] if d >= D["hy_start"] else (2.3 * D["baa"][i] - 1.0 if D["baa"][i] is not None else None)
    cred = "n" if hy is None else "r" if hy >= 5 else "y" if hy >= 4 else "g"
    L = [rate, emp, liq, cred]
    reds = L.count("r"); yel = L.count("y")
    mode = "수비" if reds >= 2 else "중립" if (reds == 1 or yel >= 2) else "공격"
    return mode, hy, L


def overheat(D, i):
    r, w, c, m, g = D["rsi"][i], D["wrsi"][i], D["c"][i], D["ma200"][i], D["gap50w"][i]
    return sum([r is not None and r >= 80, w is not None and w >= 75, m is not None and c / m - 1 >= 0.15, g is not None and g >= 120])


class Acct:
    def __init__(s): s.u = {}

    def val(s, P, i, fx):
        return sum(q * P[t][i] for t, q in s.u.items()) * fx

    def buy(s, t, krw, P, i, fx):
        if krw <= 0: return
        s.u[t] = s.u.get(t, 0) + krw / fx / P[t][i]

    def sell(s, t, krw, P, i, fx):
        q = min(s.u.get(t, 0), krw / fx / P[t][i]); s.u[t] = s.u.get(t, 0) - q
        return q * P[t][i] * fx

    def v(s, t, P, i, fx): return s.u.get(t, 0) * P[t][i] * fx


def run(D, i0, end=None, cfg=None):
    cfg = cfg or {}
    P, fx_, dates = D["P"], D["fx"], D["dates"]
    end = end or len(dates) - 1
    A = {k: Acct() for k in ("longterm", "ammo", "swing", "irp", "pension")}
    fx = fx_[i0]
    # 초기 잔고
    A["irp"].buy("SGOV", INIT["irp"] * 0.5644, P, i0, fx)
    A["irp"].buy("SPY", INIT["irp"] * 0.4356 * 0.55, P, i0, fx)
    A["irp"].buy("QQQ", INIT["irp"] * 0.4356 * 0.45, P, i0, fx)
    A["pension"].buy("SPY", INIT["pension"] * 0.64, P, i0, fx)
    A["pension"].buy("QQQ", INIT["pension"] * 0.23, P, i0, fx)
    A["pension"].buy("SGOV", INIT["pension"] * 0.13, P, i0, fx)
    A["swing"].buy("SGOV", INIT["swing"], P, i0, fx)
    principal = sum(INIT.values())
    flows = [(dates[i0], -principal)]
    ammo_done, lt_done = set(), set()
    cyc_min = 0; boost = {'ammo': {}, 'longterm': {}}; boosts_in_cycle = 0; prev_st = None; armed_low = None
    lt_last_sell = -10 ** 9
    sw_pos = {}  # t: {"avg":px, "half":bool, "lots":n, "last":i}
    sw_last_oh = -10 ** 9
    last_month = None
    curve, prin_curve, log = [], [], []
    for i in range(i0, end + 1):
        d = dates[i]; fx = fx_[i]
        dd = D["dd"][i]; st = D["states"][i] or 2
        stage = 4 if dd <= -30 else 3 if dd <= -20 else 2 if dd <= -15 else 1 if dd <= -10 else 0
        mode, hy, L = macro(D, i)
        nolev = mode == "수비" or (hy is not None and hy >= 6)
        oh = overheat(D, i)
        rsi = D["rsi"][i]; vix = D["vix"][i]
        c, m200, m60 = D["c"][i], D["ma200"][i], D["ma60"][i]
        aux = sum([rsi is not None and rsi <= 40, vix is not None and vix >= 20,
                   (m200 is not None and c <= m200 * 1.01) or (m60 is not None and c <= m60 * 1.01)])
        # ---------- 매월 25일 이후 첫 거래일: 적립 ----------
        ym = d[:7]
        if i > i0 and int(d[8:]) >= 25 and ym != last_month:
            last_month = ym
            add = sum(MONTHLY.values()); principal += add; flows.append((d, -add))
            # 장투
            row = next(r for r in MONTHLY_RULES if dd > r[0])
            al = {"QQQ": row[1], "SPY": row[2], "QLD": row[3], "TQQQ": row[4]}

            def mv(a, b, x):
                x = min(al.get(a, 0), x)
                al[a] = al.get(a, 0) - x; al[b] = al.get(b, 0) + x
            if mode == "중립":
                if stage == 0: mv("SPY", "SCHD", 30); mv("QLD", "SGOV", al["QLD"] / 2)
                else:
                    l = (al["QLD"] + al["TQQQ"]) / 2; t = al["TQQQ"]; mv("TQQQ", "QQQ", t); mv("QLD", "QQQ", max(0, l - t))
            elif nolev:
                if stage == 4:
                    l = al["QLD"] + al["TQQQ"]; mv("TQQQ", "QQQ", al["TQQQ"]); mv("QLD", "QQQ", al["QLD"]); mv("QQQ", "SGOV", l / 2)
                else:
                    mv("QLD", "SGOV", al["QLD"]); mv("TQQQ", "SGOV", al["TQQQ"]); mv("QQQ", "SGOV", 20); mv("SPY", "SCHD", 30)
            if oh >= 2: mv("QLD", "SGOV", al.get("QLD", 0))
            lt = A["longterm"]; ltv = lt.val(P, i, fx) / MAN
            curlev = (lt.v("QLD", P, i, fx) + lt.v("TQQQ", P, i, fx)) / MAN
            maxlev = max(0, 0.30 * (ltv + 200) - curlev); newlev = al.get("QLD", 0) + al.get("TQQQ", 0)
            if newlev > maxlev + 0.5:
                cut = newlev - maxlev; r = cut; tq = min(al.get("TQQQ", 0), r); al["TQQQ"] = al.get("TQQQ", 0) - tq; r -= tq
                al["QLD"] = max(0, al.get("QLD", 0) - r); al["QQQ"] += cut
            for t, man in al.items():
                lt.buy(t, man * MAN, P, i, fx)
            # 분기 30% 상한 정리
            if d[5:7] in ("03", "06", "09", "12"):
                ltv = lt.val(P, i, fx); lev = lt.v("QLD", P, i, fx) + lt.v("TQQQ", P, i, fx)
                if ltv and lev > 0.30 * ltv:
                    x = lev - 0.30 * ltv; got = lt.sell("TQQQ", x, P, i, fx); got += lt.sell("QLD", x - got, P, i, fx); lt.buy("QQQ", got, P, i, fx)
            # 현금
            A["ammo"].buy("SGOV", MONTHLY["ammo"], P, i, fx)
            # 연금저축
            w = (65, 35) if stage >= 1 else (55, 45)
            A["pension"].buy("QQQ", MONTHLY["pension"] * w[0] / 100, P, i, fx)
            A["pension"].buy("SPY", MONTHLY["pension"] * w[1] / 100, P, i, fx)
            # IRP 위험자산 목표
            irp = A["irp"]; iv = irp.val(P, i, fx); risk = irp.v("SPY", P, i, fx) + irp.v("QQQ", P, i, fx)
            lo, hi = (cfg.get('irp5') if st == 5 and cfg.get('irp5') else IRP_T.get(st, (55, 60))); rp = risk / iv * 100
            if rp < lo:
                x = (lo - rp) / 100 * iv; got = irp.sell("SGOV", x, P, i, fx); irp.buy("SPY", got * 0.55, P, i, fx); irp.buy("QQQ", got * 0.45, P, i, fx)
            elif rp > hi:
                x = (rp - hi) / 100 * iv; sv = irp.v("SPY", P, i, fx); qv = irp.v("QQQ", P, i, fx)
                got = irp.sell("SPY", x * sv / risk, P, i, fx) + irp.sell("QQQ", x * qv / risk, P, i, fx); irp.buy("SGOV", got, P, i, fx)
        # ---------- 현금 계좌 차수 (일별) ----------
        am = A["ammo"]
        for n, (lvl, rem, mix) in enumerate(AMMO_T, 1):
            if n in ammo_done: continue
            if dd <= lvl and aux >= 2:
                amt = am.sell("SGOV", am.v("SGOV", P, i, fx) * rem / 100, P, i, fx)
                mx = {"QQQ": 100} if nolev else mix
                for t, w in mx.items(): am.buy(t, amt * w / 100, P, i, fx)
                ammo_done.add(n); log.append((d, f"현금 {n}차 {round(amt / MAN)}만"))
            break
        if dd > -1:
            inv = [t for t in am.u if t != "SGOV" and am.u[t] > 1e-12]
            if inv:
                tot = 0
                for t in inv:
                    v = am.v(t, P, i, fx); half = am.sell(t, v / 2, P, i, fx); am.buy("SGOV", half, P, i, fx)
                    q = am.u[t]; am.u[t] = 0; A["longterm"].u[t] = A["longterm"].u.get(t, 0) + q; tot += v
                log.append((d, f"현금 회복 정산 {round(tot / MAN)}만"))
            ammo_done.clear()
        # ---------- 장투 현금 풀 (SGOV) 낙폭 투입 ----------
        lt = A["longterm"]
        for n, (lvl, rem, mix) in enumerate(LT_POOL_T, 1):
            if n in lt_done: continue
            if dd <= lvl and lt.u.get("SGOV", 0) > 0:
                amt = lt.sell("SGOV", lt.v("SGOV", P, i, fx) * rem / 100, P, i, fx)
                mx = {"QQQ": 100} if nolev else mix
                for t, w in mx.items(): lt.buy(t, amt * w / 100, P, i, fx)
                lt_done.add(n)
            break
        if dd > -1:
            lt_done.clear()
            if lt.u.get("TQQQ", 0) > 0:
                got = lt.sell("TQQQ", lt.v("TQQQ", P, i, fx), P, i, fx); lt.buy("QQQ", got, P, i, fx)
        # 장투 과열 3개+: QLD 20% → SGOV (126일 쿨다운)
        if oh >= 3 and i - lt_last_sell >= 126 and lt.u.get("QLD", 0) > 0:
            got = lt.sell("QLD", lt.v("QLD", P, i, fx) * 0.2, P, i, fx); lt.buy("SGOV", got, P, i, fx); lt_last_sell = i
            log.append((d, f"장투 과열 QLD 20% 매도 {round(got / MAN)}만"))
        # ---------- 반등 가속 (시나리오 검증용) ----------
        cyc_min = min(cyc_min, dd)
        if cfg.get("trigger") and dd > -1:
            cyc_min = 0; boosts_in_cycle = 0; boost = {"ammo": {}, "longterm": {}}
        if cfg.get("trigger"):
            if cfg["trigger"] == "ma200":
                fire = st == 5 and prev_st in (3, 4) and cyc_min <= cfg.get("min_dd", -20)
            else:  # 저점 대비 +N% 반등
                lowpx = min(D["c"][max(0, i - 252):i + 1])
                fire = cyc_min <= cfg.get("min_dd", -20) and c >= lowpx * (1 + cfg["trigger"] / 100) and not any(boost[k] for k in boost)
            if fire and boosts_in_cycle < cfg.get("max_boosts", 2):
                for k in ("ammo", "longterm"):
                    acc = A[k]; amt = acc.sell("SGOV", acc.v("SGOV", P, i, fx) * cfg.get("frac", 0.5), P, i, fx)
                    for t, w in cfg.get("mix", {"QLD": 100}).items():
                        q0 = acc.u.get(t, 0); acc.buy(t, amt * w / 100, P, i, fx); boost[k][t] = boost[k].get(t, 0) + acc.u.get(t, 0) - q0
                boosts_in_cycle += 1; log.append((d, f"반등 가속 {boosts_in_cycle}회"))
            # 손절: 다시 추세이탈(200일선 -3% 2일)이면 가속분만 SGOV로
            if cfg.get("stop") and st in (3, 4) and prev_st not in (3, 4) and any(boost[k] for k in boost):
                for k in ("ammo", "longterm"):
                    acc = A[k]
                    for t, q in boost[k].items():
                        q = min(q, acc.u.get(t, 0)); got = q * P[t][i] * fx; acc.u[t] = acc.u.get(t, 0) - q; acc.buy("SGOV", got, P, i, fx)
                    boost[k] = {}
                log.append((d, "반등 가속 손절"))
        prev_st = st
        # ---------- 스윙 ----------
        sw = A["swing"]; swv = sw.val(P, i, fx); unit = swv * 0.05 * (0.5 if mode == "수비" else 1)
        qchg = (D["c"][i] / D["c"][i - 1] - 1) * 100 if i else 0
        vs200 = (c / m200 - 1) * 100 if m200 else None
        sxc = (P["SOXX"][i] / P["SOXX"][i - 1] - 1) * 100 if i else 0
        sigs = {
            "QQQ": qchg <= -2 and rsi is not None and rsi <= 45,
            "QLD": (qchg <= -2 and rsi is not None and rsi <= 40) or (vs200 is not None and vs200 <= -5),
            "SOXX": sxc <= -4 or (D["sdd52"][i] <= -25 and D["srsi"][i] is not None and D["srsi"][i] <= 35),
        }
        tp = {"QQQ": (5, 9), "QLD": (8, 15), "SOXX": (8, 15)}
        for t, on in sigs.items():
            p = sw_pos.get(t)
            if on and oh < 2 and (not p or (p["lots"] < 3 and i - p["last"] >= 5)):
                amt = sw.sell("SGOV", unit, P, i, fx)
                if amt > 0:
                    q0 = sw.u.get(t, 0); sw.buy(t, amt, P, i, fx); q1 = sw.u[t]
                    avg = ((p["avg"] * q0) if p else 0) + P[t][i] * (q1 - q0)
                    sw_pos[t] = {"avg": avg / q1, "half": False, "lots": (p["lots"] if p else 0) + 1, "last": i}
            p = sw_pos.get(t)
            if p and sw.u.get(t, 0) > 0:
                g = (P[t][i] / p["avg"] - 1) * 100
                if not p["half"] and g >= tp[t][0]:
                    got = sw.sell(t, sw.v(t, P, i, fx) / 2, P, i, fx); sw.buy("SGOV", got, P, i, fx); p["half"] = True
                elif p["half"] and g >= tp[t][1]:
                    got = sw.sell(t, sw.v(t, P, i, fx), P, i, fx); sw.buy("SGOV", got, P, i, fx); del sw_pos[t]
        if oh >= 2 and i - sw_last_oh >= 21 and sw.u.get("QLD", 0) > 0:
            frac = 1.0 if oh >= 4 else 0.5 if oh >= 3 else 0.3
            got = sw.sell("QLD", sw.v("QLD", P, i, fx) * frac, P, i, fx); sw.buy("SGOV", got, P, i, fx); sw_last_oh = i
            if frac == 1.0: sw_pos.pop("QLD", None)
        tot = sum(a.val(P, i, fx) for a in A.values())
        curve.append(tot); prin_curve.append(principal)
    return dict(curve=curve, prin=prin_curve, flows=flows, A=A, log=log, i0=i0, end=end)


def bench(D, i0, t, end=None):
    P, fx_, dates = D["P"], D["fx"], D["dates"]; end = end or len(dates) - 1
    u = sum(INIT.values()) / fx_[i0] / P[t][i0]; last = None; curve = []
    for i in range(i0, end + 1):
        d = dates[i]
        if i > i0 and int(d[8:]) >= 25 and d[:7] != last:
            last = d[:7]; u += sum(MONTHLY.values()) / fx_[i] / P[t][i]
        curve.append(u * P[t][i] * fx_[i])
    return curve


def xirr(flows, final_d, final_v):
    fl = flows + [(final_d, final_v)]
    t0 = datetime.strptime(fl[0][0], "%Y-%m-%d")
    ts = [((datetime.strptime(d, "%Y-%m-%d") - t0).days / 365.25, v) for d, v in fl]
    f = lambda r: sum(v / (1 + r) ** t for t, v in ts)
    lo, hi = -0.99, 2.0
    if f(lo) * f(hi) > 0: return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return round(mid * 100, 2)


def metrics(D, r, bq, bs):
    dates = D["dates"]; i0 = r["i0"]; cv, pc = r["curve"], r["prin"]
    n = len(cv)

    def at(k):
        if k >= n: return None
        d = dates[i0 + k]
        fl = [x for x in r["flows"] if x[0] <= d]
        return {"date": d, "value_man": round(cv[k] / MAN), "principal_man": round(pc[k] / MAN),
                "ret_pct": round((cv[k] / pc[k] - 1) * 100, 1), "irr": xirr(fl, d, cv[k]),
                "qqq_all_ret_pct": round((bq[k] / pc[k] - 1) * 100, 1), "spy_all_ret_pct": round((bs[k] / pc[k] - 1) * 100, 1)}

    def mdd(curve, upto):
        pk, m, md = curve[0], 0, None
        for k in range(min(upto, len(curve))):
            pk = max(pk, curve[k])
            if curve[k] / pk - 1 < m: m = curve[k] / pk - 1; md = dates[i0 + k]
        return round(m * 100, 1), md

    def under(curve):
        """원금(누적 투입) 대비 가장 깊이 빠진 구간: 원금 아래로 내려간 날 → 다시 원금 이상 회복한 날"""
        g = [curve[k] / pc[k] - 1 for k in range(len(curve))]
        kw = min(range(len(g)), key=lambda k: g[k])
        if g[kw] >= 0: return {"months": 0, "worst_vs_principal_pct": round(g[kw] * 100, 1)}
        ks = kw
        while ks > 0 and g[ks - 1] < 0: ks -= 1
        ke = next((k for k in range(kw, len(g)) if g[k] >= 0), None)
        return {"from": dates[i0 + ks], "to": dates[i0 + ke] if ke else None, "months": round(((ke if ke else len(g)) - ks) / 21),
                "worst_vs_principal_pct": round(g[kw] * 100, 1), "worst_date": dates[i0 + kw], "unrecovered": ke is None}

    def peak_rec(curve):
        """총평가액이 시작 후 최고점에서 빠졌다가 그 최고점을 되찾기까지(최대 낙폭 구간 기준)"""
        pk, pk_k, best = curve[0], 0, None
        cur_dd_start = None
        worst = 0
        res = None
        for k in range(len(curve)):
            if curve[k] >= pk:
                if cur_dd_start is not None and res and res.get("to") is None and res["peak_k"] == pk_k:
                    res["to"] = dates[i0 + k]; res["months"] = round((k - pk_k) / 21)
                pk, pk_k = curve[k], k; cur_dd_start = None
            else:
                cur_dd_start = pk_k
                g = curve[k] / pk - 1
                if g < worst:
                    worst = g; res = {"peak": dates[i0 + pk_k], "peak_k": pk_k, "trough": dates[i0 + k], "to": None}
        if res: res.pop("peak_k", None)
        return res

    horizon = {"1y": at(252), "3y": at(756), "5y": at(1260), "10y": at(2520), "end": at(n - 1)}
    win = min(n, 1260)  # MDD는 시작 후 5년 기준 + 전체
    return {
        "horizon": horizon,
        "mdd_5y": mdd(cv, win), "mdd_all": mdd(cv, n),
        "qqq_all_mdd_5y": mdd(bq, win), "spy_all_mdd_5y": mdd(bs, win),
        "underwater": under(cv), "qqq_all_underwater": under(bq), "spy_all_underwater": under(bs),
        "peak_recovery": peak_rec(cv),
        "accounts_end_5y_man": None,
    }


def main():
    y, f = load()
    D = prep(y, f)
    dates = D["dates"]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dd_window_days": DD_WIN, "data_start": dates[0],
           "hy_fred_start": D["hy_start"], "notes": [
               "시작 잔고·월 적립은 현재(2026) 금액 그대로, 물가 조정 없음", "세금·수수료·환전 스프레드 제외",
               "QLD·TQQQ 상장 전은 QQQ 일간 2·3배 − (보수 0.95% + 차입 T-bill) 합성", "SCHD 2011 이전은 SPY, SOXX 2001 이전은 ^SOX(가격지수)",
               "SGOV·머니마켓은 3개월 T-bill 이자", "IRP·연금저축 국내상장 ETF는 미국 지수 × 원달러 환율로 근사",
               "스윙은 QQQM·QLD·SOXX 규칙만(빅테크는 현재 종목 기준이라 생존 편향 → 제외, 3배 관심 규칙 제외)",
               "IRP KODEX 200 음봉 매매 제외", "공포탐욕 과거값 없음 → 과열 4개 신호, 보조지표 3개 중 2개",
               "HY 스프레드 FRED 시작 전은 BAA10Y×2.3−1.0 근사", "순유동성(2002년 12월 이전 자료 없음)은 '판정 불가'로 둠"],
           "scenarios": []}
    for name, a, b in SCEN:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k])
        r = run(D, i0)
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        m = metrics(D, r, bq, bs)
        k5 = min(len(r["curve"]) - 1, 1260); i5 = i0 + k5
        # 계좌별 5년 시점 평가는 재실행으로 계산
        r5 = run(D, i0, i5)
        m["accounts_end_5y_man"] = {k: round(v.val(D["P"], i5, D["fx"][i5]) / MAN) for k, v in r5["A"].items()}
        m["holdings_5y"] = {k: {t: round(q * D["P"][t][i5] * D["fx"][i5] / MAN) for t, q in v.u.items() if q > 1e-12} for k, v in r5["A"].items()}
        qqq_low = min(range(i0, min(len(dates), i0 + 1500)), key=lambda k: D["c"][k])
        rec = next((k for k in range(qqq_low, len(dates)) if D["c"][k] >= D["c"][i0]), None)
        m.update({"name": name, "start": dates[i0], "qqq_peak": round(D["c"][i0], 2),
                  "qqq_trough": dates[qqq_low], "qqq_trough_dd": round((D["c"][qqq_low] / D["c"][i0] - 1) * 100, 1),
                  "qqq_recover": dates[rec] if rec else None, "fx_start": round(D["fx"][i0], 1),
                  "events": r5["log"][:40]})
        out["scenarios"].append(m)
        print(json.dumps({k: m[k] for k in ("name", "start", "mdd_5y", "underwater", "qqq_all_underwater")}, ensure_ascii=False), flush=True)
    VARIANTS = [
        ("현재 규칙", {}),
        ("A 200일선 회복 시 현금 50%→QQQ, 손절", {"trigger": "ma200", "frac": 0.5, "mix": {"QQQ": 100}, "stop": True}),
        ("B 200일선 회복 시 현금 50%→QLD, 손절", {"trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}),
        ("C 200일선 회복 시 현금 100%→QQQ·QLD 반반, 손절", {"trigger": "ma200", "frac": 1.0, "mix": {"QQQ": 50, "QLD": 50}, "stop": True}),
        ("D 저점 +20% 반등 시 현금 50%→QLD, 손절", {"trigger": 20, "frac": 0.5, "mix": {"QLD": 100}, "stop": True}),
        ("E = B + IRP 회복기 위험자산 65~70%", {"trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True, "irp5": (65, 70)}),
        ("F = B에서 손절 없음", {"trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": False}),
        ("G IRP 회복기 65~70%만", {"irp5": (65, 70)}),
    ]
    out["variants"] = []
    for name, a, b in SCEN:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k])
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        for vname, cfg in VARIANTS:
            r = run(D, i0, cfg=cfg)
            m = metrics(D, r, bq, bs)
            out["variants"].append({"scenario": name, "variant": vname, "start": dates[i0],
                                    "worst": m["underwater"].get("worst_vs_principal_pct"), "uw_months": m["underwater"].get("months"),
                                    "mdd5": m["mdd_5y"][0], "y1": (m["horizon"]["1y"] or {}).get("ret_pct"), "y3": (m["horizon"]["3y"] or {}).get("ret_pct"),
                                    "y5": (m["horizon"]["5y"] or {}).get("ret_pct"), "end": m["horizon"]["end"]["ret_pct"], "irr_end": m["horizon"]["end"]["irr"],
                                    "events": [e for e in r["log"] if "반등" in e[1]][:12]})
            print(name, vname, out["variants"][-1]["worst"], out["variants"][-1]["uw_months"], out["variants"][-1]["y3"], out["variants"][-1]["y5"], out["variants"][-1]["end"], flush=True)
    json.dump(out, open(os.path.join(B.DATA, "portfolio_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ok")


if __name__ == "__main__":
    main()
