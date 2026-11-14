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
AMMO_T = [(-25, 5, {"QQQ": 80, "QLD": 20}), (-30, 10.5, {"QQQ": 70, "QLD": 30}), (-35, 17.6, {"QQQ": 60, "QLD": 40}),
          (-40, 21.4, {"QQQ": 50, "QLD": 50}), (-50, 45.5, {"QLD": 80, "QQQ": 20}), (-60, 100, {"QLD": 80, "TQQQ": 20})]  # 11-08 개정
LT_POOL_T = [(-10, 10, {"QQQ": 70, "QLD": 30}), (-15, 22.2, {"QQQ": 60, "QLD": 40}),
             (-20, 42.9, {"QLD": 80, "QQQ": 20}), (-30, 100, {"QLD": 80, "TQQQ": 20})]
DD_WIN = int(os.environ.get("DD_WIN", "1260"))
DIVS = ("SCHD", "JEPI", "DIVO", "JEPQ")
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
    for s in ["QQQ", "SPY", "QLD", "TQQQ", "SCHD", "DVY", "JEPI", "DIVO", "JEPQ", "SOXX", "^SOX", "^VIX", "^IRX"] + (["^BXM", "^BXN"] if (os.environ.get("ONLY_DIV") or os.environ.get("ONLY_N2")) else []) + (["GC=F", "GLD"] if (os.environ.get("ONLY_PARK") or os.environ.get("ONLY_W40") or os.environ.get("ONLY_N2") or os.environ.get("ONLY_BTC") or os.environ.get("ONLY_GSW")) else []) + (["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA"] if os.environ.get("ONLY_SWING") else []) + (["BTC-USD", "BITO"] if os.environ.get("ONLY_BTC") else []):
        try:
            y[s] = B.yahoo(s, "max"); print("yahoo", s, len(y[s]), flush=True)
        except Exception as e:
            print("yahoo fail", s, e, flush=True); y[s] = []
        time.sleep(0.4)
    f = {}
    for k, sid in {"fx": "DEXKOUS", "ft_old": "DFEDTAR", "ft_new": "DFEDTARU", "dgs2": "DGS2", "dgs10": "DGS10", "sahm": "SAHMREALTIME",
                   "icsa": "ICSA", "walcl": "WALCL", "tga": "WTREGEN", "rrp": "RRPONTSYD", "hy": "BAMLH0A0HYM2", "baa": "BAA10Y", "margin": "BOGZ1FL663067003Q"}.items():
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
    dvy_map = dict((r[0], r[5]) for r in y.get("DVY", []))
    dvy = [dvy_map.get(d) for d in dates]
    P = {
        "QQQ": [a / adj[0] * 100 for a in adj],
        "SPY": [s / spy[0] * 100 for s in spy],
        "QLD": splice(dates, qret, [(r[0], r[5]) for r in y["QLD"]], 2, [(0.0095 + rf[i]) / 252 for i in range(n)]),
        "TQQQ": splice(dates, qret, [(r[0], r[5]) for r in y["TQQQ"]], 3, [(0.0095 + 2 * rf[i]) / 252 for i in range(n)]),
        # SCHD: 실제(2011-10~) → DVY(2003-11~, 배당 ETF 대용) → SPY
        "SCHD": splice(dates, [0] + [(lambda a, b: (b / a - 1) if a and b else sret[k])(dvy[k - 1], dvy[k]) for k in range(1, n)], [(r[0], r[5]) for r in y["SCHD"]]),
        "SOXX": splice(dates, soxret, [(r[0], r[5]) for r in y["SOXX"]]),
    }
    sg = [100.0]
    for i in range(1, n):
        sg.append(sg[-1] * (1 + rf[i - 1] / 252))
    P["SGOV"] = sg
    # SOXL 합성: SOXX 일간 3배 − (보수 0.95% + 차입 2×T-bill)
    sxr = [0] + [P["SOXX"][k] / P["SOXX"][k - 1] - 1 for k in range(1, n)]
    P["SOXL"] = splice(dates, sxr, [], 3, [(0.0095 + 2 * rf[k]) / 252 for k in range(n)])
    # 금: GLD(2004-11~) 수익률 우선, 그 전은 금 선물 GC=F, 그 전(2000-08 이전)은 첫 값으로 고정
    gc = dict((r[0], r[4]) for r in y.get("GC=F", []) if r[4])
    if gc:
        gv = ff(list(gc.items()), dates); first = next(v for v in gv if v); gv = [v or first for v in gv]
        gr = [0] + [gv[k] / gv[k - 1] - 1 for k in range(1, n)]
        P["GOLD"] = splice(dates, gr, [(r[0], r[5]) for r in y.get("GLD", [])])
    # 상장 이후만 존재하는 배당·커버드콜 ETF (상장 전 None)
    for t in ("JEPI", "DIVO", "JEPQ") + tuple(x for x in ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA"] if x in y):
        mp = dict((r[0], r[5]) for r in y.get(t, []))
        P[t] = [mp.get(d) for d in dates]
        # 휴장 차이로 빈 날 직전값
        last = None
        for k in range(n):
            if P[t][k] is None and last is not None: P[t][k] = last
            last = P[t][k] if P[t][k] is not None else last
    # 배당안 연구용: JEPI·JEPQ 상장 전 대용 (실데이터 우선)
    #  JEPI_X: CBOE S&P500 BuyWrite(^BXM) → 없으면 SPY×0.6 + 단기금리×0.4
    #  JEPQ_X: CBOE 나스닥100 BuyWrite(^BXN) → 없으면 QQQ×0.75 + 단기금리×0.25
    D_PROXY = {}
    for t, bx, base, k in (("JEPI", "^BXM", sret, 0.6), ("JEPQ", "^BXN", qret, 0.75)):
        bxm = dict((r[0], r[4]) for r in y.get(bx, []) if r[4])
        if len(bxm) > 2000:
            bv = ff(list(bxm.items()), dates)
            br = [0] + [(bv[k2] / bv[k2 - 1] - 1) if bv[k2] and bv[k2 - 1] else base[k2] for k2 in range(1, n)]
            P[t + "_X"] = splice(dates, br, [(r[0], r[5]) for r in y.get(t, [])]); D_PROXY[t] = bx
        else:
            br = [k * base[k2] + (1 - k) * rf[k2 - 1] / 252 if k2 else 0 for k2 in range(n)]
            P[t + "_X"] = splice(dates, br, [(r[0], r[5]) for r in y.get(t, [])]); D_PROXY[t] = f"{'SPY' if t == 'JEPI' else 'QQQ'}x{k}"
    V200 = {}
    for t in ("SCHD", "JEPI", "DIVO", "JEPQ"):
        arr = P[t]; out = [None] * n; run_sum = 0; cnt = 0; win = []
        for k in range(n):
            v = arr[k]
            if v is None: win = []; run_sum = 0; continue
            win.append(v); run_sum += v
            if len(win) > 200: run_sum -= win.pop(0)
            if len(win) == 200: out[k] = (v / (run_sum / 200) - 1) * 100
        V200[t] = out
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
    dv = P["SCHD"]; divdd52 = [(dv[i] / max(dv[max(0, i - 251):i + 1]) - 1) * 100 for i in range(n)]
    qdd52 = [(c[i] / max(c[max(0, i - 251):i + 1]) - 1) * 100 for i in range(n)]
    # 거시
    ft = sorted(f["ft_old"] + f["ft_new"])
    ft_d = ff(ft, dates)
    changes = [(ft[i][0], ft[i][1] - ft[i - 1][1]) for i in range(1, len(ft)) if abs(ft[i][1] - ft[i - 1][1]) > 1e-9]
    dgs2 = ff(f["dgs2"], dates); sahm = ff(f["sahm"], dates); dgs10 = ff(f.get("dgs10") or [], dates)
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
    # 미국 빚투(연준 가계 마진 대출) 전년 대비, 과거 40분기 대비 상위 10% 여부. 분기 시작일 + 5개월 뒤부터 사용(발표 지연)
    mg = f.get("margin") or []
    mh = []
    for k in range(4, len(mg)):
        if not mg[k - 4][1]: continue
        yoy = mg[k][1] / mg[k - 4][1] - 1
        hist = [mg[j][1] / mg[j - 4][1] - 1 for j in range(max(4, k - 40), k) if mg[j - 4][1]]
        hot = len(hist) >= 12 and sum(x <= yoy for x in hist) / len(hist) >= 0.9
        y_, m_ = int(mg[k][0][:4]), int(mg[k][0][5:7]) + 5
        if m_ > 12: y_ += 1; m_ -= 12
        mh.append((f"{y_:04d}-{m_:02d}-01", hot))
    mhot = ff(mh, dates)
    return dict(mhot=mhot, dates=dates, c=c, P=P, fx=fx, rf=rf, rsi=rsi, wrsi=wrsi_d, gap50w=gap_d, ma200=ma200, ma60=ma60, vix=vix,
                states=states, dd=dd, srsi=srsi, sdd52=sdd52, divdd52=divdd52, v200=V200, qdd52=qdd52, ft=ft_d, changes=changes, dgs2=dgs2, dgs10=dgs10, sahm=sahm, ic4=ic4,
                hy=hy, hy_start=hy_start, baa=baa, nl=nl_d, proxy=D_PROXY)


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
    A = {k: Acct() for k in ("longterm", "ammo", "swing", "irp", "pension", "gold", "sw40")}
    PC = cfg.get("park") == "C"; c_done = False
    GOLD = cfg.get("gold", 0); LT_AMT = 200 - GOLD
    BC = cfg.get("bigcut"); bc_on = False; bc_sold = {}; bc_i0 = None; bc_wait = False
    big = [datetime.strptime(x[0], "%Y-%m-%d") for x in D["changes"] if x[1] <= -0.5]
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
    mswap = False
    div_last = -10 ** 9
    sw_pos = {}  # t: {"avg":px, "half":bool, "lots":n, "last":i}
    sw_last_oh = -10 ** 9
    last_month = None
    curve, prin_curve, log = [], [], []
    ltf, ltc = [], []
    sw_b = True; sw_ok = 0; sw_cnt = [0, 0]
    CG = cfg.get("gate") == "conf"; LEVC = cfg.get("lev_conf"); GG = cfg.get("gap_gate"); gst = False; INST = cfg.get("sw40_inst", "QLD"); s4_tr = []; s4_stop = [0]; s4_div = [0.0]   # 8주 지속 데드(확인된 하락 추세) 게이트
    SW40 = cfg.get("sw40"); s4_lots = []; s4_prin = 0.0; s4_n = [0, 0]   # (d) Ben 11-14: 40주선 아래에선 장투 적립 일부를 스윙(QLD 단타)으로
    W = cfg.get("w40"); lev_sold = {"longterm": 0.0, "ammo": 0.0}; one_sold = 0.0   # QQQ 주봉 40주선 신호 (11-14 Ben 검증)
    for i in range(i0, end + 1):
        d = dates[i]; fx = fx_[i]
        dd = D["dd"][i]; st = D["states"][i] or 2
        stage = 4 if dd <= -30 else 3 if dd <= -20 else 2 if dd <= -15 else 1 if dd <= -10 else 0
        mode, hy, L = macro(D, i)
        nolev = mode == "수비" or (hy is not None and hy >= 6)
        oh = overheat(D, i)
        # 빅컷(0.5%p 이상 한 번에 인하) 후 45일 안전장치
        if BC:
            dt = datetime.strptime(d, "%Y-%m-%d"); inwin = any(0 <= (dt - b).days <= 45 for b in big)
            if inwin and not bc_on:
                bc_on = True; bc_i0 = i; log.append((d, "빅컷 안전장치 시작"))
                if BC == "sell":   # 장투 주식을 20%까지 줄임 → SGOV
                    lt_ = A["longterm"]; tv = lt_.val(P, i, fx); stk = {t: lt_.v(t, P, i, fx) for t in lt_.u if t != "SGOV" and lt_.u[t] > 1e-12}
                    st_v = sum(stk.values()); cut = max(0, st_v - 0.2 * tv)
                    for t, v in stk.items():
                        got = lt_.sell(t, cut * v / st_v, P, i, fx); bc_sold[t] = bc_sold.get(t, 0) + got; lt_.buy("SGOV", got, P, i, fx)
                    log.append((d, f"빅컷 매도 {round(cut / MAN)}만"))
            if bc_on and BC in ("stage", "stage_ma", "stage_s5") and (i - bc_i0) in (0, 5, 10):   # 2주 3단계: 장투 주식 70% → 50% → 30% (레버리지부터)
                tgt = {0: 0.7, 5: 0.5, 10: 0.3}[i - bc_i0]
                lt_ = A["longterm"]; tv = lt_.val(P, i, fx)
                stk = {t: lt_.v(t, P, i, fx) for t in lt_.u if t != "SGOV" and lt_.u[t] > 1e-12}
                cut = max(0, sum(stk.values()) - tgt * tv)
                for t in sorted(stk, key=lambda t: 0 if t in ("TQQQ", "QLD") else 1):
                    if cut <= 0: break
                    got = lt_.sell(t, min(cut, lt_.v(t, P, i, fx)), P, i, fx); cut -= got
                    bc_sold[t] = bc_sold.get(t, 0) + got; lt_.buy("SGOV", got, P, i, fx)
            if not inwin and bc_on:
                bc_on = False
                if bc_sold and BC in ("stage_ma", "stage_s5"):   # 날짜 대신 추세 회복을 기다림 (그사이 낙폭 사다리는 재개)
                    bc_wait = True; log.append((d, "빅컷 복귀 대기(추세 조건)"))
                elif bc_sold:   # 45일 뒤 판 만큼 다시 매수
                    lt_ = A["longterm"]
                    for t, v in bc_sold.items(): lt_.buy(t, lt_.sell("SGOV", v, P, i, fx), P, i, fx)
                    bc_sold = {}
                log.append((d, "빅컷 안전장치 종료"))
        if bc_wait and not bc_on:
            cq, mq = D["c"][i], D["ma200"][i]
            ok = mq is not None and (cq > mq if BC == "stage_ma" else (D["states"][i] == 5 or cq > mq * 1.03))
            if ok:
                lt_ = A["longterm"]; avail = lt_.v("SGOV", P, i, fx); tot = sum(bc_sold.values()) or 1
                for t, v in bc_sold.items(): lt_.buy(t, lt_.sell("SGOV", min(v, avail * v / tot), P, i, fx), P, i, fx)
                bc_sold = {}; bc_wait = False; log.append((d, "빅컷 복귀(추세 회복)"))
        rsi = D["rsi"][i]; vix = D["vix"][i]
        c, m200, m60 = D["c"][i], D["ma200"][i], D["ma60"][i]
        aux = sum([rsi is not None and rsi <= 40, vix is not None and vix >= 20,
                   (m200 is not None and c <= m200 * 1.01) or (m60 is not None and c <= m60 * 1.01)])
        up = True; wx = 0
        if W or SW40 or LEVC:
            u = D["w40"][i]; up = True if u is None else u; wx = D["w40x"][i]
        conf = bool(D.get("w40c") and D["w40c"][i])
        bear = conf if CG else (not up)
        if GG is not None:   # 11-14 Ben: 데드 + 40주선 하향 이격도 ≤ GG면 스윙 모드, 골든까지 유지
            gp = D["gap40"][i]
            if wx == 1 or up: gst = False
            elif gp is not None and gp <= GG: gst = True
            bear = gst
        if SW40 and wx == 1:   # 골든: 스윙 계좌에 남은 현금은 장투로(QQQ60·SPY40)
            s4 = A["sw40"]; got = s4.sell("SGOV", s4.v("SGOV", P, i, fx), P, i, fx)
            if got > 0: A["longterm"].buy("QQQ", got * 0.6, P, i, fx); A["longterm"].buy("SPY", got * 0.4, P, i, fx); ltf.append((d, -got)); s4_prin = max(0.0, s4_prin - got)
        if W:
            if wx == -1:   # 데드: 주봉 종가가 40주선 아래로 마감 → 레버리지 전량 SGOV (Ben안은 1배도 30%)
                for k in ("longterm", "ammo"):
                    acc = A[k]; got = acc.sell("QLD", acc.v("QLD", P, i, fx), P, i, fx) + acc.sell("TQQQ", acc.v("TQQQ", P, i, fx), P, i, fx)
                    acc.buy("SGOV", got, P, i, fx); lev_sold[k] += got
                if W == "ben":
                    lt_ = A["longterm"]
                    got = sum(lt_.sell(t, lt_.v(t, P, i, fx) * 0.3, P, i, fx) for t in list(lt_.u) if t not in ("SGOV", "QLD", "TQQQ") and lt_.u[t] > 1e-12)
                    lt_.buy("SGOV", got, P, i, fx); one_sold += got
                log.append((d, "40주선 데드"))
            elif wx == 1:   # 골든: 판 만큼 되사기 (Ben안은 남은 장투 SGOV 50%도 QQQ70·QLD30)
                for k in ("longterm", "ammo"):
                    acc = A[k]; x = min(lev_sold[k], acc.v("SGOV", P, i, fx)); acc.buy("QLD", acc.sell("SGOV", x, P, i, fx), P, i, fx); lev_sold[k] = 0.0
                if W == "ben":
                    lt_ = A["longterm"]; x = min(one_sold, lt_.v("SGOV", P, i, fx)); got = lt_.sell("SGOV", x, P, i, fx)
                    lt_.buy("QQQ", got * 0.6, P, i, fx); lt_.buy("SPY", got * 0.4, P, i, fx); one_sold = 0.0
                    got = lt_.sell("SGOV", lt_.v("SGOV", P, i, fx) * 0.5, P, i, fx); lt_.buy("QQQ", got * 0.7, P, i, fx); lt_.buy("QLD", got * 0.3, P, i, fx)
                log.append((d, "40주선 골든"))
        # ---------- 매월 25일 이후 첫 거래일: 적립 ----------
        ym = d[:7]
        if i > i0 and int(d[8:]) >= 25 and ym != last_month:
            last_month = ym
            add = sum(MONTHLY.values()); principal += add; flows.append((d, -add)); ltf.append((d, -LT_AMT * MAN))
            if GOLD: A["gold"].buy("GOLD", GOLD * MAN, P, i, fx)
            if PC:   # 박종훈 원형: 장투+현금 몫을 SGOV(닻)/지수(돛)로, 레버리지 없음
                new = (LT_AMT + MONTHLY["ammo"] / MAN) * MAN
                sgf = 0.0 if dd <= -30 else (cfg["c_split"][1] if oh >= 2 else cfg["c_split"][0])
                A["ammo"].buy("SGOV", new * sgf, P, i, fx)
                A["longterm"].buy("QQQ", new * (1 - sgf) * 0.5, P, i, fx); A["longterm"].buy("SPY", new * (1 - sgf) * 0.5, P, i, fx)
            else:
                # 장투
                row = next(r for r in MONTHLY_RULES if dd > r[0])
                if cfg.get("m10") and row[0] == -15: row = (-15,) + tuple(cfg["m10"])
                al = {"QQQ": row[1], "SPY": row[2], "QLD": row[3], "TQQQ": row[4]}
                if cfg.get("div") and stage == 0:   # 평상 구간: 1배 일부를 배당 ETF로
                    b = cfg["div"]; al["QQQ"] -= b[0]; al["SPY"] -= b[1]; al["SCHD"] = b[0] + b[1]
                divt = "SCHD"
                if cfg.get("div_pool"):   # 그달 200일선 대비 가장 싼 배당 ETF
                    cands = [(D["v200"][t][i], t) for t in cfg["div_pool"] if D["v200"][t][i] is not None]
                    if cands: divt = min(cands)[1]
                if GOLD: al = {k: v * LT_AMT / 200 for k, v in al.items()}
                useB = True
                if cfg.get("switch") and stage == 0:   # B↔A 스위칭: 매달 적립일에만 판정(신규 적립금만 바뀌고 보유분 매매 없음)
                    cs = D["c"][max(0, i - 19):i + 1]; mu = sum(cs) / len(cs); sd = (sum((x - mu) ** 2 for x in cs) / len(cs)) ** 0.5
                    pb = (c_ := D["c"][i]) and ((c_ - (mu - 2 * sd)) / (4 * sd) * 100 if sd else 50)
                    m2 = D["ma200"][i]; v2 = (c_ / m2 - 1) * 100 if m2 else 0; t10 = D["dgs10"][i]; rr = D["rsi"][i] or 50
                    chart = [oh >= 1, rr >= 65, pb >= 80, v2 >= 8]; mac = [mode != "공격", t10 is not None and t10 >= 4.5]
                    sv = cfg["switch"]
                    if sv == "score": pts = sum(chart) + sum(mac)
                    elif sv == "macro": pts = 2 * any(mac)
                    elif sv == "chart": pts = 2 * any(chart)
                    elif sv == "cheap": pts = 0 if (dd <= -5 and mode == "공격") else 2
                    else: pts = 2
                    if pts >= 2: sw_b = True; sw_ok = 0
                    elif pts == 0:
                        sw_ok += 1
                        if sw_ok >= cfg.get("sw_hold", 2): sw_b = False
                    useB = sw_b; sw_cnt[0 if useB else 1] += 1
                if cfg.get("normal") and stage == 0 and useB:   # 평상: 장투 몫을 SGOV:주식 비율로 (과열 2개+면 두 번째 비율)
                    sg = cfg["normal"][1] if oh >= 2 else cfg["normal"][0]; stk = LT_AMT * (1 - sg)
                    al = {"SGOV": LT_AMT * sg, "QQQ": stk * 0.4, "SPY": stk * 0.3, "SCHD": stk * 0.3, "QLD": 0, "TQQQ": 0}
                if cfg.get("n2") and stage == 0 and useB and oh < 2:   # 11-14 Ben 질문: 평상을 0~−5 / −5~−10 두 단계로, SGOV 일부 → SPYM·JEPI
                    sg, sp, jp = cfg["n2"][0 if dd > -5 else 1]; stk = LT_AMT * (1 - sg - sp - jp)
                    al = {"SGOV": LT_AMT * sg, "QQQ": stk * 0.4, "SPY": stk * 0.3 + LT_AMT * sp, "SCHD": stk * 0.3, "JEPI_X": LT_AMT * jp, "QLD": 0, "TQQQ": 0}
                if W == "ben":   # 40주선 우선: 위면 평상에도 −10% 구간 비율(전액 주식), 아래면 낙폭과 관계없이 SGOV 7:3
                    if up and stage == 0: al = {"QQQ": 85 * LT_AMT / 200, "SPY": 85 * LT_AMT / 200, "QLD": 30 * LT_AMT / 200, "TQQQ": 0}
                    elif not up:
                        stk = LT_AMT * 0.3; al = {"SGOV": LT_AMT * 0.7, "QQQ": stk * 0.4, "SPY": stk * 0.3, "SCHD": stk * 0.3, "QLD": 0, "TQQQ": 0}

                def mv(a, b, x):
                    x = min(al.get(a, 0), x)
                    al[a] = al.get(a, 0) - x; al[b] = al.get(b, 0) + x
                if mode == "중립":
                    if stage == 0: mv("SPY", "SCHD", 30); mv("QLD", "SGOV", al.get("QLD", 0) / 2)
                    else:
                        l = (al["QLD"] + al["TQQQ"]) / 2; t = al["TQQQ"]; mv("TQQQ", "QQQ", t); mv("QLD", "QQQ", max(0, l - t))
                elif nolev:
                    if stage == 4:
                        l = al["QLD"] + al["TQQQ"]; mv("TQQQ", "QQQ", al["TQQQ"]); mv("QLD", "QQQ", al["QLD"]); mv("QQQ", "SGOV", l / 2)
                    else:
                        mv("QLD", "SGOV", al["QLD"]); mv("TQQQ", "SGOV", al["TQQQ"]); mv("QQQ", "SGOV", 20); mv("SPY", "SCHD", 30)
                if oh >= 2 and cfg.get("div"):   # 과열: QLD 몫 절반은 배당, 절반은 SGOV / 3개+면 QQQM 20도 배당
                    q = al.get("QLD", 0); mv("QLD", "SCHD", q / 2); mv("QLD", "SGOV", q / 2)
                    if oh >= 3: mv("QQQ", "SCHD", 20)
                elif oh >= 2: mv("QLD", "SGOV", al.get("QLD", 0))
                if cfg.get("margin") and D["mhot"][i] and st in (3, 4):   # 빚투 극단 + 추세이탈 이하: 신규 레버리지 → QQQ
                    mv("TQQQ", "QQQ", al.get("TQQQ", 0)); mv("QLD", "QQQ", al.get("QLD", 0))
                mcond = bool(D["mhot"][i]) and st in (3, 4)
                if cfg.get("margin") == "swap":   # 조건 첫 진입 시 보유 레버리지도 QQQ로 1회 교체
                    if mcond and not mswap:
                        ltA = A["longterm"]; got = ltA.sell("TQQQ", ltA.v("TQQQ", P, i, fx), P, i, fx) + ltA.sell("QLD", ltA.v("QLD", P, i, fx), P, i, fx)
                        ltA.buy("QQQ", got, P, i, fx); mswap = True; log.append((d, f"빚투 경보: 장투 레버리지 {round(got / MAN)}만 → QQQ"))
                    elif not mcond:
                        mswap = False
                if (W and not up) or (LEVC and conf): mv("TQQQ", "QQQ", al.get("TQQQ", 0)); mv("QLD", "QQQ", al.get("QLD", 0))
                lt = A["longterm"]; ltv = lt.val(P, i, fx) / MAN
                curlev = (lt.v("QLD", P, i, fx) + lt.v("TQQQ", P, i, fx)) / MAN
                maxlev = max(0, 0.30 * (ltv + LT_AMT) - curlev); newlev = al.get("QLD", 0) + al.get("TQQQ", 0)
                if newlev > maxlev + 0.5:
                    cut = newlev - maxlev; r = cut; tq = min(al.get("TQQQ", 0), r); al["TQQQ"] = al.get("TQQQ", 0) - tq; r -= tq
                    al["QLD"] = max(0, al.get("QLD", 0) - r); al["QQQ"] += cut
                if bc_on: al = {"SGOV": sum(al.values())}   # 빅컷 45일: 신규 장투 적립 전액 SGOV
                if SW40 and bear:
                    x = sum(al.values()) * SW40; al = {k: v * (1 - SW40) for k, v in al.items()}
                    A["sw40"].buy("SGOV", x * MAN, P, i, fx); s4_prin += x * MAN; ltf.append((d, x * MAN)); s4_div[0] += x
                for t, man in al.items():
                    lt.buy(divt if t == "SCHD" else t, man * MAN, P, i, fx)
                # 분기 30% 상한 정리
                if d[5:7] in ("03", "06", "09", "12"):
                    ltv = lt.val(P, i, fx); lev = lt.v("QLD", P, i, fx) + lt.v("TQQQ", P, i, fx)
                    if ltv and lev > 0.30 * ltv:
                        x = lev - 0.30 * ltv; got = lt.sell("TQQQ", x, P, i, fx); got += lt.sell("QLD", x - got, P, i, fx); lt.buy("QQQ", got, P, i, fx)
                # 현금
                af = cfg.get("ammo_frac", 1.0)
                A["ammo"].buy("SGOV", MONTHLY["ammo"] * af, P, i, fx)
                if af < 1:   # 현금 몫 축소분은 장투에서 1배 지수(QQQ 60·SPY 40)로 바로 매수
                    lt.buy("QQQ", MONTHLY["ammo"] * (1 - af) * 0.6, P, i, fx); lt.buy("SPY", MONTHLY["ammo"] * (1 - af) * 0.4, P, i, fx)
            # 연금저축
            w = (65, 35) if stage >= 1 else (55, 45)
            A["pension"].buy("QQQ", MONTHLY["pension"] * w[0] / 100, P, i, fx)
            A["pension"].buy("SPY", MONTHLY["pension"] * w[1] / 100, P, i, fx)
            # IRP 위험자산 목표
            irp = A["irp"]; iv = irp.val(P, i, fx); risk = irp.v("SPY", P, i, fx) + irp.v("QQQ", P, i, fx)
            lo, hi = (cfg.get('irp5') if st == 5 and cfg.get('irp5') else IRP_T.get(st, (55, 60)))
            if W == "ben": lo, hi = (65, 70) if up else (45, 50)
            rp = risk / iv * 100
            if rp < lo:
                x = (lo - rp) / 100 * iv; got = irp.sell("SGOV", x, P, i, fx); irp.buy("SPY", got * 0.55, P, i, fx); irp.buy("QQQ", got * 0.45, P, i, fx)
            elif rp > hi:
                x = (rp - hi) / 100 * iv; sv = irp.v("SPY", P, i, fx); qv = irp.v("QQQ", P, i, fx)
                got = irp.sell("SPY", x * sv / risk, P, i, fx) + irp.sell("QQQ", x * qv / risk, P, i, fx); irp.buy("SGOV", got, P, i, fx)
        # ---------- 현금 계좌 차수 (일별) ----------
        am = A["ammo"]
        if PC:   # −30% 첫 도달: 닻(SGOV)의 75% → 나스닥·S&P500 반반. 전고점 −1% 이내 회복 시 재무장
            if dd <= -30 and not c_done:
                amt = am.sell("SGOV", am.v("SGOV", P, i, fx) * cfg.get("c_deploy", 0.75), P, i, fx)
                A["longterm"].buy("QQQ", amt / 2, P, i, fx); A["longterm"].buy("SPY", amt / 2, P, i, fx)
                c_done = True; log.append((d, f"닻 투입 {round(amt / MAN)}만"))
            if dd > -1: c_done = False
        for n, (lvl, rem, mix) in enumerate([] if (PC or bc_on) else AMMO_T, 1):
            if n in ammo_done: continue
            if dd <= lvl and aux >= 2 and (W != "ben" or up):
                amt = am.sell("SGOV", am.v("SGOV", P, i, fx) * rem / 100, P, i, fx)
                mx = {"QQQ": 100} if (nolev or (W and not up) or (LEVC and conf)) else mix
                for t, w in mx.items(): am.buy(t, amt * w / 100, P, i, fx)
                ammo_done.add(n); log.append((d, f"현금 {n}차 {round(amt / MAN)}만"))
            break
        if dd > -1:
            inv = [t for t in am.u if t != "SGOV" and am.u[t] > 1e-12]
            if inv:
                tot = 0
                for t in inv:
                    v = am.v(t, P, i, fx); half = am.sell(t, v / 2, P, i, fx); am.buy("SGOV", half, P, i, fx)
                    q = am.u[t]; am.u[t] = 0; A["longterm"].u[t] = A["longterm"].u.get(t, 0) + q; tot += v; ltf.append((d, -(v - half)))
                log.append((d, f"현금 회복 정산 {round(tot / MAN)}만"))
            ammo_done.clear()
        # ---------- 장투 현금 풀 (SGOV) 낙폭 투입 ----------
        lt = A["longterm"]
        for n, (lvl, rem, mix) in enumerate([] if (PC or bc_on or cfg.get("no_ladder")) else LT_POOL_T, 1):
            if n in lt_done: continue
            if dd <= lvl and lt.u.get("SGOV", 0) > 0 and (W != "ben" or up):
                amt = lt.sell("SGOV", lt.v("SGOV", P, i, fx) * rem / 100, P, i, fx)
                mx = {"QQQ": 100} if (nolev or (W and not up) or (LEVC and conf)) else mix
                for t, w in mx.items(): lt.buy(t, amt * w / 100, P, i, fx)
                lt_done.add(n)
            break
        if dd > -1:
            lt_done.clear()
            if lt.u.get("TQQQ", 0) > 0:
                got = lt.sell("TQQQ", lt.v("TQQQ", P, i, fx), P, i, fx); lt.buy("QQQ", got, P, i, fx)
        # 배당 → 성장 교체: QQQ 1년 고점 -15% 이하인데 배당 ETF가 10%p 이상 덜 빠졌으면 배당 보유분 30% 매도 → QQQM(폭락이면 QLD 절반)
        if cfg.get("div_sell") and D["qdd52"][i] <= -15 and D["divdd52"][i] - D["qdd52"][i] >= 10 and i - div_last >= 126 and any(lt.u.get(t, 0) > 0 for t in DIVS):
            got = sum(lt.sell(t, lt.v(t, P, i, fx) * 0.3, P, i, fx) for t in DIVS if lt.u.get(t, 0) > 0)
            mx = {"QQQ": 50, "QLD": 50} if (stage == 4 and not nolev) else {"QQQ": 100}
            for t, w in mx.items(): lt.buy(t, got * w / 100, P, i, fx)
            div_last = i; log.append((d, f"배당→성장 교체 {round(got / MAN)}만"))
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
        # ---------- (d) 40주선 아래 QLD 단타: QQQ RSI ≤ 30이면 계좌 25%씩(최대 4개, 5거래일 간격), +5% 절반·+10% 나머지·−10% 손절·10거래일 청산 ----------
        if SW40:
            s4 = A["sw40"]; qp = P[INST][i] * fx
            if bear and rsi is not None and rsi <= 30 and len(s4_lots) < 4 and (not s4_lots or i - s4_lots[-1]["i"] >= 5):
                amt = s4.sell("SGOV", min(s4.val(P, i, fx) * 0.25, s4.v("SGOV", P, i, fx)), P, i, fx)
                if amt > 0:
                    q0 = s4.u.get(INST, 0); s4.buy(INST, amt, P, i, fx); s4_lots.append({"q": s4.u[INST] - q0, "px": P[INST][i], "i": i, "half": False, "cost": amt, "got": 0.0})
            keep = []
            for lot in s4_lots:
                g = P[INST][i] / lot["px"] - 1; sellq = 0
                if g <= -0.10 or i - lot["i"] >= 10: sellq = lot["q"]; s4_n[1 if g > 0 else 0] += 1; s4_stop[0] += g <= -0.10
                elif not lot["half"] and g >= 0.05: sellq = lot["q"] / 2; lot["half"] = True
                elif lot["half"] and g >= 0.10: sellq = lot["q"]; s4_n[1] += 1
                if sellq:
                    got = s4.sell(INST, sellq * qp, P, i, fx); s4.buy("SGOV", got, P, i, fx); lot["q"] -= sellq; lot["got"] += got
                if lot["q"] > 1e-12: keep.append(lot)
                else: s4_tr.append(round((lot["got"] / lot["cost"] - 1) * 100, 2) if lot["cost"] else 0)
            s4_lots = keep
            if not s4_lots and s4_prin > 0:
                v4 = s4.val(P, i, fx)
                if v4 > s4_prin * 1.02:   # 다 정리했고 이익이면 이익의 50% → 장투(QQQ)
                    got = s4.sell("SGOV", (v4 - s4_prin) * 0.5, P, i, fx); A["longterm"].buy("QQQ", got, P, i, fx); ltf.append((d, -got)); s4_prin += 0
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
        ltc.append((A["longterm"].val(P, i, fx), A["longterm"].v("SGOV", P, i, fx), stage))
    return dict(curve=curve, prin=prin_curve, flows=flows, A=A, log=log, i0=i0, end=end, ltf=ltf, ltc=ltc, sw=sw_cnt, s4=s4_n, s4_tr=s4_tr, s4_stop=s4_stop[0], s4_div=s4_div[0])


# ================= 통합 4종목 전략 (SPYM·QQQM·SGOV·QLD) =================
# 현금 계좌(월 85만)는 기존 규칙 그대로. 나머지(장투·스윙·IRP·연금저축)는 한 덩어리, 월 245만.
UNI = {
    # 국면: (SPY, QQQ, SGOV, QLD) 목표 비중 %
    "U0": {"base": (33, 33, 34, 0), "signals": False},
    "U1": {"base": (33, 33, 34, 0), "hot2": (30, 30, 40, 0), "hot3": (25, 25, 50, 0),
           "dd10": (30, 35, 20, 15), "dd20": (25, 35, 10, 30), "dd30": (20, 35, 0, 45), "recov": (25, 35, 10, 30), "signals": True},
    "U0S": {"base": (33, 33, 34, 0), "signals": False, "eq": "SCHD"},
    "U2": {"base": (30, 35, 30, 5), "hot2": (30, 30, 40, 0), "hot3": (25, 25, 50, 0),
           "dd10": (25, 35, 15, 25), "dd20": (20, 30, 5, 45), "dd30": (15, 25, 0, 60), "recov": (20, 35, 5, 40), "signals": True},
}


UNI["U1S"] = {**UNI["U1"], "eq": "SCHD"}
UNI["QS"] = {"base": (50, 50, 0, 0), "signals": False, "eq": "SCHD"}
UNI["QP"] = {"base": (50, 50, 0, 0), "signals": False}


def uni_target(cfg, dd, oh, mode, hy, recov):
    if not cfg["signals"]:
        return cfg["base"]
    if dd <= -30: w = cfg["dd30"]
    elif dd <= -20: w = cfg["dd20"]
    elif dd <= -10: w = cfg["dd10"]
    elif recov: w = cfg["recov"]
    elif oh >= 3: w = cfg["hot3"]
    elif oh >= 2: w = cfg["hot2"]
    else: w = cfg["base"]
    sp, qq, sg, ql = w
    nolev = mode == "수비" or (hy is not None and hy >= 6)
    if nolev:   # 거시 우선: QLD 몫 SGOV로 (폭락 -30% 이하면 절반만)
        cut = ql / 2 if dd <= -30 else ql
        ql -= cut; sg += cut
    elif mode == "중립":
        cut = ql / 4; ql -= cut; sg += cut
    return (sp, qq, sg, ql)


def run_unified(D, i0, key, end=None):
    cfg = UNI[key]
    P, fx_, dates = D["P"], D["fx"], D["dates"]
    end = end or len(dates) - 1
    core, am = Acct(), Acct()
    fx = fx_[i0]
    principal = sum(INIT.values())
    tw = cfg["base"]
    AS = (cfg.get("eq", "SPY"), "QQQ", "SGOV", "QLD")
    for t, w in zip(AS, tw):
        core.buy(t, principal * w / 100, P, i0, fx)
    flows = [(dates[i0], -principal)]
    ammo_done = set(); last_month = None; curve, prin, log = [], [], []
    cyc_min = 0; recov = False; last_tier = 0; trades = 0
    for i in range(i0, end + 1):
        d = dates[i]; fx = fx_[i]; dd = D["dd"][i]; st = D["states"][i] or 2
        mode, hy, _ = macro(D, i); oh = overheat(D, i)
        nolev = mode == "수비" or (hy is not None and hy >= 6)
        rsi, vix = D["rsi"][i], D["vix"][i]; c, m200, m60 = D["c"][i], D["ma200"][i], D["ma60"][i]
        aux = sum([rsi is not None and rsi <= 40, vix is not None and vix >= 20,
                   (m200 is not None and c <= m200 * 1.01) or (m60 is not None and c <= m60 * 1.01)])
        cyc_min = min(cyc_min, dd)
        if dd > -1: cyc_min = 0; recov = False
        if cyc_min <= -20 and st == 5: recov = True   # -20% 이상 빠진 뒤 200일선 회복 → 전고점까지 회복 국면
        tier = 3 if dd <= -30 else 2 if dd <= -20 else 1 if dd <= -10 else 0
        monthly = i > i0 and int(d[8:]) >= 25 and d[:7] != last_month
        # 리밸런싱 시점: 매월 적립일 + 하락 단계가 깊어지는 날(공포 구간 즉시 대응)
        rebal = monthly or (cfg["signals"] and tier > last_tier)
        if monthly:
            last_month = d[:7]
            add = sum(MONTHLY.values()); principal += add; flows.append((d, -add))
            core.buy("SGOV", MONTHLY["longterm"] + MONTHLY["pension"], P, i, fx)
            am.buy("SGOV", MONTHLY["ammo"], P, i, fx)
        if rebal:
            tw = uni_target(cfg, dd, oh, mode, hy, recov)
            tot = core.val(P, i, fx)
            cur = {t: core.v(t, P, i, fx) for t in AS}
            for t, w in zip(AS, tw):   # 매도 먼저 → SGOV
                tgt = tot * w / 100
                if t != "SGOV" and cur[t] > tgt * 1.02:
                    core.buy("SGOV", core.sell(t, cur[t] - tgt, P, i, fx), P, i, fx); trades += 1
            for t, w in zip(AS, tw):
                tgt = tot * w / 100
                if t != "SGOV" and cur[t] < tgt * 0.98:
                    core.buy(t, core.sell("SGOV", tgt - cur[t], P, i, fx), P, i, fx); trades += 1
            if tier != last_tier and tier > last_tier: log.append((d, f"하락 {tier}단계 리밸런싱 {tw}"))
        if monthly or tier > last_tier or tier == 0: last_tier = tier if (tier > last_tier or monthly) else last_tier
        if tier == 0: last_tier = 0
        # 현금 계좌 (기존 규칙)
        for n, (lvl, rem, mix) in enumerate(AMMO_T, 1):
            if n in ammo_done: continue
            if dd <= lvl and aux >= 2:
                amt = am.sell("SGOV", am.v("SGOV", P, i, fx) * rem / 100, P, i, fx)
                for t, w in ({"QQQ": 100} if nolev else mix).items(): am.buy(t, amt * w / 100, P, i, fx)
                ammo_done.add(n)
            break
        if dd > -1:
            for t in [t for t in am.u if t != "SGOV" and am.u[t] > 1e-12]:
                v = am.v(t, P, i, fx); am.buy("SGOV", am.sell(t, v / 2, P, i, fx), P, i, fx)
                q = am.u[t]; am.u[t] = 0; core.buy("SGOV", q * P[t][i] * fx, P, i, fx)   # 이관분은 통합 계좌 비중에 맞춰 다음 리밸런싱
            ammo_done.clear()
        curve.append(core.val(P, i, fx) + am.val(P, i, fx)); prin.append(principal)
    return dict(curve=curve, prin=prin, flows=flows, i0=i0, end=end, log=log, trades=trades,
                A={"core": core, "ammo": am})


def bench(D, i0, t, end=None):
    P, fx_, dates = D["P"], D["fx"], D["dates"]; end = end or len(dates) - 1
    u = sum(INIT.values()) / fx_[i0] / P[t][i0]; last = None; curve = []
    for i in range(i0, end + 1):
        d = dates[i]
        if i > i0 and int(d[8:]) >= 25 and d[:7] != last:
            last = d[:7]; u += sum(MONTHLY.values()) / fx_[i] / P[t][i]
        curve.append(u * P[t][i] * fx_[i])
    return curve


def run_simple(D, i0, mix, ammo=True, irp_risk=70, end=None, ladder=None, delever=False, lad_pension=False, pen_mix=None, irp_mix=None, heat=None):
    """단순안: 1배 지수 고정 적립(매도 없음) + IRP 위험 70%(연 1회 리밸런싱) + 현금 계좌 6단계(ammo=False면 현금 몫도 지수 적립)."""
    P, fx_, dates = D["P"], D["fx"], D["dates"]
    end = end or len(dates) - 1
    core, irp, am = Acct(), Acct(), Acct()
    fx = fx_[i0]
    principal = sum(INIT.values())
    def buymix(acct, amt, i, fx):
        for t, w in mix.items(): acct.buy(t, amt * w / 100, P, i, fx)
    pm, im = pen_mix or mix, irp_mix or mix
    pen = Acct() if pen_mix else core
    def buyw(acct, amt, i, fx, w_):
        for t, w in w_.items(): acct.buy(t, amt * w / 100, P, i, fx)
    buyw(pen, INIT["pension"], i0, fx, pm); buymix(core, INIT["swing"], i0, fx)
    buyw(irp, INIT["irp"] * irp_risk / 100, i0, fx, im); irp.buy("SGOV", INIT["irp"] * (100 - irp_risk) / 100, P, i0, fx)
    flows = [(dates[i0], -principal)]
    heat_last = None
    ammo_done = set(); last_month = None; last_year = dates[i0][:4]; curve, prin, log = [], [], []
    for i in range(i0, end + 1):
        d = dates[i]; fx = fx_[i]; dd = D["dd"][i]
        mode, hy, _ = macro(D, i)
        nolev = mode == "수비" or (hy is not None and hy >= 6)
        rsi, vix = D["rsi"][i], D["vix"][i]; c, m200, m60 = D["c"][i], D["ma200"][i], D["ma60"][i]
        aux = sum([rsi is not None and rsi <= 40, vix is not None and vix >= 20,
                   (m200 is not None and c <= m200 * 1.01) or (m60 is not None and c <= m60 * 1.01)])
        if i > i0 and int(d[8:]) >= 25 and d[:7] != last_month:
            last_month = d[:7]
            add = sum(MONTHLY.values()); principal += add; flows.append((d, -add))
            if ladder:   # 하락 단계별 레버리지 사다리: 장투 몫만 적용, 연금은 1배
                lm = next((m for lvl, m in ladder if dd <= lvl), mix)
                for t, w in lm.items(): core.buy(t, MONTHLY["longterm"] * w / 100, P, i, fx)
                if lad_pension:   # 연금은 레버리지 불가 → QLD 몫은 QQQ
                    for t, w in lm.items(): core.buy("QQQ" if t == "QLD" else t, MONTHLY["pension"] * w / 100, P, i, fx)
                else:
                    buyw(pen, MONTHLY["pension"], i, fx, pm)
            else:
                buymix(core, MONTHLY["longterm"], i, fx); buyw(pen, MONTHLY["pension"], i, fx, pm)
            if ammo: am.buy("SGOV", MONTHLY["ammo"], P, i, fx)
            else: buymix(core, MONTHLY["ammo"], i, fx)
        if d[:4] != last_year:   # IRP 연 1회 위험 70% 리밸런싱
            last_year = d[:4]; tot = irp.val(P, i, fx); risk = tot - irp.v("SGOV", P, i, fx); tgt = tot * irp_risk / 100
            if risk > tgt:
                for t in im: irp.buy("SGOV", irp.sell(t, (risk - tgt) * im[t] / 100, P, i, fx), P, i, fx)
            elif risk < tgt:
                buyw(irp, irp.sell("SGOV", tgt - risk, P, i, fx), i, fx, im)
        if ammo:
            for n, (lvl, rem, amix) in enumerate(AMMO_T, 1):
                if n in ammo_done: continue
                if dd <= lvl and aux >= 2:
                    amt = am.sell("SGOV", am.v("SGOV", P, i, fx) * rem / 100, P, i, fx)
                    for t, w in ({"QQQ": 100} if nolev else amix).items(): am.buy(t, amt * w / 100, P, i, fx)
                    ammo_done.add(n); log.append((d, f"현금 {n}차"))
                break
            if dd > -1 and ammo_done:
                for t in [t for t in am.u if t != "SGOV" and am.u[t] > 1e-12]:
                    v = am.v(t, P, i, fx); am.buy("SGOV", am.sell(t, v / 2, P, i, fx), P, i, fx)
                    v2 = am.v(t, P, i, fx); buymix(core, am.sell(t, v2, P, i, fx), i, fx)
                ammo_done.clear()
        if delever and dd > -1 and core.u.get("QLD", 0) > 1e-12:   # 전고점 회복 시 QLD → QQQ
            got = core.sell("QLD", core.v("QLD", P, i, fx), P, i, fx); core.buy("QQQ", got, P, i, fx); log.append((d, f"QLD {round(got / MAN)}만 → QQQ"))
        if heat and core.u.get("QLD", 0) > 1e-12 and overheat(D, i) >= 3 and (heat_last is None or i - heat_last >= 126):
            # 과열 3점↑: 장투 QLD 전부 매도 → 평상 배당 몫(heat="div") 또는 SGOV(heat="sgov"), 6개월 휴지
            heat_last = i; got = core.sell("QLD", core.v("QLD", P, i, fx), P, i, fx)
            if heat == "sgov": core.buy("SGOV", got, P, i, fx)
            else:
                dv = {t: w for t, w in mix.items() if t not in ("QQQ", "SPY", "QLD")} or {"SCHD": 100}; sw = sum(dv.values())
                for t, w in dv.items(): core.buy(t, got * w / sw, P, i, fx)
            log.append((d, f"과열 QLD {round(got / MAN)}만 → {heat}"))
        curve.append(core.val(P, i, fx) + irp.val(P, i, fx) + am.val(P, i, fx) + (pen.val(P, i, fx) if pen is not core else 0)); prin.append(principal)
    return dict(curve=curve, prin=prin, flows=flows, i0=i0, end=end, log=log, A={"core": core, "irp": irp, "ammo": am, "pen": pen})


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


def ddwin_study(D):
    """낙폭 기준 고점 창 비교: 5년/7년/10년/사상 최고가. 채택 규칙(L)로 4대 위기 시작."""
    from collections import deque
    dates, c = D["dates"], D["c"]
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    def ddser(win):
        dq, out = deque(), []
        for k, x in enumerate(c):
            while dq and c[dq[-1]] <= x: dq.pop()
            dq.append(k)
            while dq[0] <= k - win: dq.popleft()
            out.append((x / c[dq[0]] - 1) * 100)
        return out
    def idx(d): return next((k for k, x in enumerate(dates) if x >= d), len(dates) - 1)
    res = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": []}
    base_dd = D["dd"]
    for wname, win in (("5년", 1260), ("7년", 1764), ("10년", 2520), ("사상 최고가", 10 ** 9)):
        D["dd"] = ddser(win)
        for name, a, b in SCEN:
            ks = [k for k, d in enumerate(dates) if a <= d <= b]
            if not ks: continue
            i0 = max(ks, key=lambda k: c[k])
            bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
            r = run(D, i0, cfg=L)
            m = metrics(D, r, bq, bs)
            row = {"window": wname, "scenario": name, "start": dates[i0], "irr_end": m["horizon"]["end"]["irr"],
                   "worst": m["underwater"].get("worst_vs_principal_pct"), "uw_months": m["underwater"].get("months"), "mdd5": m["mdd_5y"][0],
                   "y5": (m["horizon"]["5y"] or {}).get("ret_pct"), "y10": (m["horizon"]["10y"] or {}).get("ret_pct"),
                   "days_dd20": sum(1 for k in range(i0, len(dates)) if D["dd"][k] <= -20),
                   "days_dd30": sum(1 for k in range(i0, len(dates)) if D["dd"][k] <= -30)}
            if name == "닷컴버블":   # 2008년 두 번째 폭락 직전 레버리지 비중과 그 구간 낙폭
                k07, k09 = idx("2007-10-31"), idx("2009-03-09")
                rr = run(D, i0, k07, cfg=L)
                tot = sum(v.val(D["P"], k07, D["fx"][k07]) for v in rr["A"].values())
                lev = sum(v.v("QLD", D["P"], k07, D["fx"][k07]) + v.v("TQQQ", D["P"], k07, D["fx"][k07]) for v in rr["A"].values())
                row["lev_share_2007_10"] = round(lev / tot * 100, 1) if tot else None
                cv = r["curve"]; s0, s1 = k07 - i0, k09 - i0
                pk = max(cv[s0 - 60:s0 + 1]); row["drop_2008"] = round((min(cv[s0:s1 + 1]) / pk - 1) * 100, 1)
                row["dd_2005_01"] = round(D["dd"][idx("2005-01-03")], 1); row["dd_2008_11"] = round(D["dd"][idx("2008-11-20")], 1)
                row["dd_2012_01"] = round(D["dd"][idx("2012-01-03")], 1)
            res["rows"].append(row); print("WIN", json.dumps(row, ensure_ascii=False), flush=True)
    D["dd"] = base_dd
    json.dump(res, open(os.path.join(B.DATA, "ddwin_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def div_study(D):
    """장투 200만 배당 중심안: 평상 배당 혼합 → 하락 단계 QQQ·QLD → 과열 시 QLD 매도. 현재 규칙(L)과 비교 → data/div_bt.json"""
    dates, P = D["dates"], D["P"]
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    PEN = {"SCHD": 60, "QQQ": 40}; IRPM = {"SPY": 40, "QQQ": 30, "SCHD": 30}
    A = {"SCHD": 40, "JEPI_X": 40, "QQQ": 20}; Bm = {"SCHD": 40, "SPY": 40, "JEPQ_X": 20}
    LA = [(-30, {"QQQ": 40, "QLD": 60}), (-20, {"QQQ": 60, "QLD": 40}), (-15, {"SCHD": 10, "JEPI_X": 10, "QQQ": 60, "QLD": 20}), (-10, {"SCHD": 20, "JEPI_X": 20, "QQQ": 50, "QLD": 10})]
    LB = [(-30, {"QQQ": 40, "QLD": 60}), (-20, {"SPY": 10, "QQQ": 50, "QLD": 40}), (-15, {"SCHD": 10, "SPY": 20, "QQQ": 50, "QLD": 20}), (-10, {"SCHD": 20, "SPY": 30, "QQQ": 40, "QLD": 10})]
    V = [("A0 SCHD40·JEPI40·QQQM20 고정", A, None, None), ("A1 A + 하락 단계 QQQ·QLD + 과열 시 QLD→배당", A, LA, "div"),
         ("A2 A + 하락 단계 QQQ·QLD + 과열 시 QLD→SGOV", A, LA, "sgov"),
         ("B0 SCHD40·SPY40·JEPQ20 고정", Bm, None, None), ("B1 B + 하락 단계 QQQ·QLD + 과열 시 QLD→배당", Bm, LB, "div"),
         ("B2 B + 하락 단계 QQQ·QLD + 과열 시 QLD→SGOV", Bm, LB, "sgov")]
    starts = SCEN + [("JEPQ 상장 후 실데이터(2022-05~)", "2022-05-04", "2022-05-06"), ("2010~", "2010-01-04", "2010-01-06")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "proxy": D["proxy"], "rows": []}
    for name, a, b in starts:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [x[0] for x in SCEN] else ks[0]
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        runs = [("현재 규칙(L)", lambda: run(D, i0, cfg=L))] + [(vn, (lambda mx=mx, ld=ld, ht=ht: run_simple(D, i0, mx, True, ladder=ld, heat=ht, pen_mix=PEN, irp_mix=IRPM))) for vn, mx, ld, ht in V]
        for vn, fn in runs:
            r = fn(); m = metrics(D, r, bq, bs); h = m["horizon"]
            row = {"scenario": name, "strategy": vn, "start": dates[i0], "irr": h["end"]["irr"], "worst": m["underwater"].get("worst_vs_principal_pct"),
                   "uw_months": m["underwater"].get("months"), "mdd5": m["mdd_5y"][0], "y3": (h["3y"] or {}).get("ret_pct"), "y5": (h["5y"] or {}).get("ret_pct"),
                   "end": h["end"]["ret_pct"], "qqq_end": h["end"]["qqq_all_ret_pct"], "spy_end": h["end"]["spy_all_ret_pct"],
                   "events": [e for e in r["log"] if "과열" in e[1]][:12]}
            if "core" in r["A"]:
                k = len(dates) - 1; core = r["A"]["core"]
                row["core_mix_end"] = {t: round(core.v(t, P, k, D["fx"][k]) / MAN) for t in core.u if core.u[t] > 1e-12}
            out["rows"].append(row); print("DIV", json.dumps({x: row[x] for x in ("scenario", "strategy", "irr", "worst", "mdd5", "end")}, ensure_ascii=False), flush=True)
    for t in ("JEPI", "JEPQ", "SCHD"):   # 대용 지수 검증: 실데이터 구간 연수익
        pass
    json.dump(out, open(os.path.join(B.DATA, "div_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def margin_study(D):
    """빚투 극단 + 추세이탈 이하일 때 장투 QLD → QQQM, 효과 비교 → data/margin_bt.json"""
    dates = D["dates"]
    base = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    V = [("현재 규칙", base), ("M 빚투 경보 시 신규 QLD → QQQM", {**base, "margin": "new"}), ("N = M + 보유 QLD도 QQQM 교체", {**base, "margin": "swap"})]
    hot_days = [dates[i] for i in range(len(dates)) if D["mhot"][i] and (i == 0 or not D["mhot"][i - 1])]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hot_starts": hot_days,
           "hot_share": round(sum(1 for x in D["mhot"] if x) / len(dates) * 100, 1), "rows": []}
    starts = [(n, a, b) for n, a, b in SCEN] + [("전체 (1999-03~)", dates[0], dates[0]), ("2010~", "2010-01-04", "2010-01-31")]
    for name, a, b in starts:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [s[0] for s in SCEN] else ks[0]
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        for vn, cfg in V:
            r = run(D, i0, cfg=cfg); m = metrics(D, r, bq, bs); h = m["horizon"]
            # 장투 계좌만 따로: 최종 평가액(만원)
            lt_end = round(r["A"]["longterm"].val(D["P"], len(dates) - 1, D["fx"][-1]) / MAN)
            out["rows"].append({"scenario": name, "variant": vn, "start": dates[i0], "worst": m["underwater"].get("worst_vs_principal_pct"),
                                "uw_months": m["underwater"].get("months"), "y1": (h["1y"] or {}).get("ret_pct"), "y3": (h["3y"] or {}).get("ret_pct"),
                                "y5": (h["5y"] or {}).get("ret_pct"), "end": h["end"]["ret_pct"], "irr": h["end"]["irr"], "lt_end_man": lt_end,
                                "events": [e for e in r["log"] if "빚투" in e[1]][:10]})
            print(name, vn, out["rows"][-1]["worst"], out["rows"][-1]["y3"], out["rows"][-1]["end"], out["rows"][-1]["irr"], lt_end, flush=True)
    json.dump(out, open(os.path.join(B.DATA, "margin_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def park_study(D):
    """박종훈식 닻·돛 배분 vs 현재 규칙 → data/park_bt.json"""
    dates, P = D["dates"], D["P"]
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    V = [("A 현재 규칙", L),
         ("A+금 현재 규칙 + 금 월17만(장투 183만)", {**L, "gold": 17}),
         ("B Ben안: 평상 SGOV7:주식3, 하락 시 기존 사다리, 금17", {**L, "gold": 17, "normal": (0.7, 0.7)}),
         ("B' 평상 3:7·과열 7:3, 하락 시 기존 사다리, 금17", {**L, "gold": 17, "normal": (0.3, 0.7)}),
         ("C 화자 원형: 평상 1:9·과열 3:7, −30%에 닻 75% 투입, 레버리지 없음, 금17", {"park": "C", "gold": 17, "c_split": (0.1, 0.3)}),
         ("C7 화자 틀 + 평상 7:3, −30%에 닻 75% 투입, 레버리지 없음, 금17", {"park": "C", "gold": 17, "c_split": (0.7, 0.7)}),
         ("B+빅컷1 = B + 빅컷 후 45일 신규 적립 SGOV·사다리 정지", {**L, "gold": 17, "normal": (0.7, 0.7), "bigcut": "new"}),
         ("B+빅컷2 = B + 빅컷 즉시 장투 주식 20%까지 매도, 45일 뒤 재매수", {**L, "gold": 17, "normal": (0.7, 0.7), "bigcut": "sell"}),
         ("B+빅컷3 = B + 빅컷 후 2주 3단계(70→50→30%, 레버리지부터), 45일 뒤 재매수", {**L, "gold": 17, "normal": (0.7, 0.7), "bigcut": "stage"}),
         ("B+빅컷4 = 빅컷3 + 복귀는 45일 지난 뒤 QQQ 200일선 위일 때(그사이 사다리 재개)", {**L, "gold": 17, "normal": (0.7, 0.7), "bigcut": "stage_ma"}),
         ("B+빅컷5 = 빅컷3 + 복귀는 45일 지난 뒤 200일선 +3% 회복(회복 상태)일 때", {**L, "gold": 17, "normal": (0.7, 0.7), "bigcut": "stage_s5"})]
    starts = SCEN + [("2010~", "2010-01-04", "2010-01-31"), ("2016~", "2016-01-04", "2016-01-31")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "gold_ok": "GOLD" in P,
           "notes": ["월 330만 동일(현금 85·연금저축 45·장투 200), 금 17만은 장투 몫에서 차감", "금은 GLD(2004-11~)→GC=F(2000-08~)→고정값, 원화 환산, 매도 없음",
                     "IRP·연금저축·스윙은 모든 안에서 현재 규칙 동일", "세금·수수료·환전 스프레드 제외", "C안 과열 30%는 신규 적립금에만 적용(보유분 매도 없음)"],
           "rows": []}
    # 빅컷 사건 연구: 0.5%p 이상 인하일 이후 45일·90일 QQQ 최저 수익률, 당시 5년 고점 대비 낙폭
    ev = []
    for cd, dl in D["changes"]:
        if dl > -0.5: continue
        k0 = next((k for k, x in enumerate(dates) if x >= cd), None)
        if k0 is None: continue
        c0 = D["c"][k0]; t0 = datetime.strptime(dates[k0], "%Y-%m-%d")
        w45 = [k for k in range(k0, len(dates)) if (datetime.strptime(dates[k], "%Y-%m-%d") - t0).days <= 45]
        w90 = [k for k in range(k0, len(dates)) if (datetime.strptime(dates[k], "%Y-%m-%d") - t0).days <= 90]
        w365 = [k for k in range(k0, len(dates)) if (datetime.strptime(dates[k], "%Y-%m-%d") - t0).days <= 365]
        ev.append({"date": cd, "delta": round(dl, 2), "dd_at_cut": round(D["dd"][k0], 1),
                   "min45": round((min(D["c"][k] for k in w45) / c0 - 1) * 100, 1), "ret45": round((D["c"][w45[-1]] / c0 - 1) * 100, 1),
                   "min90": round((min(D["c"][k] for k in w90) / c0 - 1) * 100, 1), "ret365": round((D["c"][w365[-1]] / c0 - 1) * 100, 1)})
    out["bigcut_events"] = ev; print("BIGCUT", json.dumps(ev, ensure_ascii=False), flush=True)
    for name, a, b in starts:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [x[0] for x in SCEN] else ks[0]
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        for vn, cfg in V:
            if cfg.get("gold") and "GOLD" not in P: continue
            r = run(D, i0, cfg=cfg); m = metrics(D, r, bq, bs); h = m["horizon"]
            k = len(dates) - 1
            row = {"scenario": name, "strategy": vn, "start": dates[i0], "irr": h["end"]["irr"], "worst": m["underwater"].get("worst_vs_principal_pct"),
                   "uw_months": m["underwater"].get("months"), "mdd5": m["mdd_5y"][0], "mdd_all": m["mdd_all"][0],
                   "y3": (h["3y"] or {}).get("ret_pct"), "y5": (h["5y"] or {}).get("ret_pct"), "y10": (h["10y"] or {}).get("ret_pct"),
                   "end": h["end"]["ret_pct"], "end_man": h["end"]["value_man"], "qqq_end": h["end"]["qqq_all_ret_pct"], "spy_end": h["end"]["spy_all_ret_pct"],
                   "qqq_irr": None, "acct_end_man": {an: round(ac.val(P, k, D["fx"][k]) / MAN) for an, ac in r["A"].items()},
                   "sgov_share_end": round(sum(ac.v("SGOV", P, k, D["fx"][k]) for ac in r["A"].values()) / r["curve"][-1] * 100, 1),
                   "events": [e for e in r["log"] if "닻" in e[1] or "현금" in e[1] or "빅컷" in e[1]][:16]}
            out["rows"].append(row); print("PARK", json.dumps({x: row[x] for x in ("scenario", "strategy", "irr", "worst", "mdd5", "end", "sgov_share_end")}, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(B.DATA, "park_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def park_verify(D):
    """A vs B 검증: 장투 계좌 단독 수익률·손실, 평상 비율, 상승장 구간 → data/park_verify.json"""
    dates, P = D["dates"], D["P"]
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    Lnt = {k: v for k, v in L.items() if k not in ("trigger", "frac", "mix", "stop")}
    V = [("A 현재 규칙(금17)", {**L, "gold": 17}),
         ("B 평상 7:3", {**L, "gold": 17, "normal": (0.7, 0.7)}),
         ("B' 평상 3:7·과열 7:3", {**L, "gold": 17, "normal": (0.3, 0.7)}),
         ("B + −10% 구간 QQQM85·SPYM85·QLD30 (Ben 11-14)", {**L, "gold": 17, "normal": (0.7, 0.7), "m10": (85, 85, 30, 0)}),
         ("S1 점수: 차트4+거시2 중 2개↑ B, 0개 2달 A", {**L, "gold": 17, "normal": (0.7, 0.7), "switch": "score"}),
         ("S2 거시만: 거시 비정상 또는 10년물≥4.5 B", {**L, "gold": 17, "normal": (0.7, 0.7), "switch": "macro"}),
         ("S3 차트만: 과열·RSI≥65·%B≥80·200일선+8% 중 1개 B", {**L, "gold": 17, "normal": (0.7, 0.7), "switch": "chart"}),
         ("S4 싸면 A: −5~−10%이고 거시 정상일 때만 A", {**L, "gold": 17, "normal": (0.7, 0.7), "switch": "cheap"})]
    win = [(n, a, b, None) for n, a, b in SCEN] + [("2010~", "2010-01-04", "2010-01-31", None), ("2016~", "2016-01-04", "2016-01-31", None),
           ("상승장 2016-01~2018-09", "2016-01-04", "2016-01-31", "2018-09-28"), ("상승장 2019-01~2021-12", "2019-01-02", "2019-01-31", "2021-12-31"),
           ("상승장 2023-01~2024-12", "2023-01-03", "2023-01-31", "2024-12-31"), ("상승장 2023-07~2025-06", "2023-07-03", "2023-07-31", "2025-06-30")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "notes": ["장투 계좌 단독: 월 183만 적립 + 현금 계좌 회복 정산 이관분을 납입으로 계산", "worst = 장투 평가액/누적 납입 최저", "normal_pct = 기간 중 QQQ 5년 고점 대비 −10% 위였던 날 비율",
                     "qqq_dca = 같은 날 같은 금액 QQQ만 적립(현금 이관 제외)"], "rows": []}
    for name, a, b, e in win:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [x[0] for x in SCEN] else ks[0]
        end = next((k for k, d in enumerate(dates) if d >= e), len(dates) - 1) if e else len(dates) - 1
        for vn, cfg in V:
            if "GOLD" not in P: break
            r = run(D, i0, end=end, cfg=cfg); ltf, ltc = r["ltf"], r["ltc"]
            if not ltf: continue
            fmap = {}
            for d, v in ltf: fmap[d] = fmap.get(d, 0) - v
            cum = 0; worst = 0; pk = 0; mdd = 0; sg = []; q = 0; qf = []
            for k, (v, s, stg) in enumerate(ltc):
                d = dates[i0 + k]; cum += fmap.get(d, 0)
                if cum > 0: worst = min(worst, v / cum - 1)
                if v > 0: sg.append(s / v)
            norm = sum(1 for x in ltc if x[2] == 0) / len(ltc)
            for d, v in ltf:
                if v == -(200 - cfg["gold"]) * MAN:
                    k = dates.index(d); q += -v / D["fx"][k] / P["QQQ"][k]; qf.append((d, v))
            qv = q * P["QQQ"][end] * D["fx"][end]
            row = {"window": name, "strategy": vn, "start": dates[i0], "end": dates[end], "lt_irr": xirr(ltf, dates[end], ltc[-1][0]),
                   "lt_worst": round(worst * 100, 1), "lt_end_man": round(ltc[-1][0] / MAN), "lt_paid_man": round(-sum(v for _, v in ltf) / MAN),
                   "normal_pct": round(norm * 100), "sgov_avg": round(sum(sg) / len(sg) * 100) if sg else None, "sgov_end": round(ltc[-1][1] / ltc[-1][0] * 100) if ltc[-1][0] else None,
                   "total_irr": xirr(r["flows"], dates[end], r["curve"][-1]), "qqq_dca_irr": xirr(qf, dates[end], qv),
                   "b_month_pct": round(r["sw"][0] / sum(r["sw"]) * 100) if sum(r["sw"]) else None, "total_worst": round(min(min(cv / pv - 1 for cv, pv in zip(r["curve"], r["prin"])), 0) * 100, 1)}
            out["rows"].append(row); print("PV", json.dumps(row, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(B.DATA, "park_verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def w40_prep(D):
    """QQQ 주봉 종가 vs 40주 이동평균. w40[i] = 마지막으로 마감한 주 기준 위(True)/아래(False), w40x[i] = 그 주 마감일에 골든(1)/데드(−1)"""
    dates, c = D["dates"], D["c"]; n = len(dates)
    wk = [datetime.strptime(d, "%Y-%m-%d").isocalendar()[:2] for d in dates]
    ends = [k for k in range(n) if k == n - 1 or wk[k + 1] != wk[k]]
    w40 = [None] * n; w40x = [0] * n; closes = []; prev = None; cur = None; j = 0
    for k in range(n):
        if j < len(ends) and ends[j] == k:
            closes.append(c[k]); j += 1
            if len(closes) >= 40:
                ma = sum(closes[-40:]) / 40; cur = c[k] > ma
                if prev is not None and cur != prev: w40x[k] = 1 if cur else -1
                prev = cur
        w40[k] = cur
    # 확인된 하락 추세: 데드 크로스 뒤 8주(마감 주 기준) 동안 골든이 없으면 그 주 마감일부터 골든까지 True
    conf = [False] * n; wb = None; on = False; j = 0; ev = []
    for k in range(n):
        if j < len(ends) and ends[j] == k:
            j += 1
            if w40x[k] == -1: wb = 0; on = False
            elif w40x[k] == 1:
                if on and ev: ev[-1]["end_k"] = k
                wb = None; on = False
            elif wb is not None and w40[k] is False:
                wb += 1
                if wb == 8 and not on: on = True; ev.append({"k": k})
        conf[k] = on
    D["w40c"] = conf
    c = D["c"]; dd = D["dd"]; evo = []
    for e in ev:
        k = e["k"]; ke = e.get("end_k", n - 1)
        seg = c[k:ke + 1]; kmin = k + seg.index(min(seg))
        f6 = c[min(n - 1, k + 126)] / c[k] - 1; f12 = c[min(n - 1, k + 252)] / c[k] - 1
        evo.append({"confirm": dates[k], "dd_at_confirm": round(dd[k], 1), "golden": dates[ke] if "end_k" in e else None,
                    "weeks_to_golden": round((ke - k) / 5) if "end_k" in e else None,
                    "further_fall_pct": round((min(seg) / c[k] - 1) * 100, 1), "low_date": dates[kmin], "dd_at_low": round(dd[kmin], 1),
                    "ret_to_golden_pct": round((c[ke] / c[k] - 1) * 100, 1) if "end_k" in e else None,
                    "ret_6m_pct": round(f6 * 100, 1), "ret_12m_pct": round(f12 * 100, 1)})
    D["w40c_events"] = evo
    D["w40"], D["w40x"] = w40, w40x
    xs = [(dates[k], w40x[k]) for k in range(n) if w40x[k]]
    # 휩쏘: 신호 뒤 8주(40거래일) 안에 반대 신호
    ks = [k for k in range(n) if w40x[k]]
    whip = sum(1 for a, b in zip(ks, ks[1:]) if b - a <= 40)
    return {"crosses": len(xs), "golden": sum(1 for _, x in xs if x == 1), "dead": sum(1 for _, x in xs if x == -1),
            "whipsaw_8w": whip, "from": dates[ends[39]] if len(ends) > 39 else None, "list": xs[-30:]}


def w40_study(D):
    """40주선 신호 비교 → data/w40_bt.json"""
    dates, P = D["dates"], D["P"]
    info = w40_prep(D); print("W40", json.dumps({k: v for k, v in info.items() if k != "list"}, ensure_ascii=False), flush=True)
    for e in D["w40c_events"]: print("CONF", json.dumps(e, ensure_ascii=False), flush=True)
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    CUR = {**L, "gold": 17, "normal": (0.7, 0.7), "m10": (85, 85, 30, 0), "bigcut": "stage_ma"}
    V = [("A 지금 규칙", CUR),
         ("E25 데드 8주 지속 구간: 장투 적립 25% → 스윙 대기(SGOV)·QLD 단타", {**CUR, "gate": "conf", "sw40": 0.25}),
         ("E50 데드 8주 지속 구간: 장투 적립 50% → 스윙 대기·QLD 단타", {**CUR, "gate": "conf", "sw40": 0.5}),
         ("F 데드 8주 지속 구간: 레버리지 신규 매수만 중단(1배로)", {**CUR, "lev_conf": True}),
         ("G = E50 + F (보수+스윙 위주)", {**CUR, "gate": "conf", "sw40": 0.5, "lev_conf": True})]
    win = [(n, a, b, None) for n, a, b in SCEN] + [("2010~", "2010-01-04", "2010-01-31", None), ("2016~", "2016-01-04", "2016-01-31", None),
           ("상승장 2016-01~2018-09", "2016-01-04", "2016-01-31", "2018-09-28"), ("상승장 2019-01~2021-12", "2019-01-02", "2019-01-31", "2021-12-31"),
           ("상승장 2023-01~2024-12", "2023-01-03", "2023-01-31", "2024-12-31"), ("2018년 4분기 급락 2018-09~2019-12", "2018-09-04", "2018-09-30", "2019-12-31")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "w40": info, "confirm_events": D["w40c_events"],
           "notes": ["전체 = 5계좌 합산(월 330만), 장투 = 장투 계좌 단독", "worst = 평가액/누적 원금 최저", "신호는 주 마지막 거래일 종가로 판정, 그날 종가에 매매",
                     "세금·수수료·환전 스프레드 제외"], "rows": []}
    for name, a, b, e in win:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [x[0] for x in SCEN] else ks[0]
        end = next((k for k, d in enumerate(dates) if d >= e), len(dates) - 1) if e else len(dates) - 1
        for vn, cfg in V:
            if "GOLD" not in P: break
            r = run(D, i0, end=end, cfg=cfg); ltf, ltc = r["ltf"], r["ltc"]
            fmap = {}
            for d, v in ltf: fmap[d] = fmap.get(d, 0) - v
            cum = 0; worst = 0
            for k, (v, s_, stg) in enumerate(ltc):
                cum += fmap.get(dates[i0 + k], 0)
                if cum > 0: worst = min(worst, v / cum - 1)
            cv = r["curve"]; pk = cv[0]; mdd = 0
            for x in cv: pk = max(pk, x); mdd = min(mdd, x / pk - 1)
            row = {"window": name, "strategy": vn, "start": dates[i0], "end": dates[end],
                   "total_irr": xirr(r["flows"], dates[end], cv[-1]), "total_worst": round(min(min(x / p - 1 for x, p in zip(cv, r["prin"])), 0) * 100, 1),
                   "total_mdd": round(mdd * 100, 1), "end_man": round(cv[-1] / MAN),
                   "lt_irr": xirr(ltf, dates[end], ltc[-1][0]) if ltf else None, "lt_worst": round(worst * 100, 1),
                   "signals": sum(1 for e_ in r["log"] if "40주선" in e_[1]), "sw40_trades": r["s4"], "sw40_end_man": round(r["A"]["sw40"].val(P, end, D["fx"][end]) / MAN)}
            out["rows"].append(row); print("W40R", json.dumps(row, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(B.DATA, "w40c_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def n2_study(D):
    """평상 2단계(0~−5 / −5~−10) SGOV 일부 → SPYM·JEPI 비교 → data/n2_bt.json"""
    D.setdefault("w40c", None)
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    CUR = {**L, "gold": 17, "normal": (0.7, 0.7), "m10": (85, 85, 30, 0), "bigcut": "stage_ma"}
    V = [("A 현행 7:3", CUR),
         ("N1 0~−5: SGOV50·SPYM10·JEPI10·주식30 / −5~−10: SGOV30·SPYM15·JEPI15·주식40", {**CUR, "n2": ((0.5, 0.1, 0.1), (0.3, 0.15, 0.15))}),
         ("N2 N1과 같은 비율, 배당칸 전부 SPYM", {**CUR, "n2": ((0.5, 0.2, 0.0), (0.3, 0.3, 0.0))}),
         ("N3 N1과 같은 비율, 배당칸 전부 JEPI", {**CUR, "n2": ((0.5, 0.0, 0.2), (0.3, 0.0, 0.3))}),
         ("N4 완만: 0~−5 SGOV60·SPYM5·JEPI5 / −5~−10 SGOV50·SPYM10·JEPI10", {**CUR, "n2": ((0.6, 0.05, 0.05), (0.5, 0.1, 0.1))})]
    win = [(n, a, b, None) for n, a, b in SCEN] + [("2010~", "2010-01-04", "2010-01-31", None), ("2016~", "2016-01-04", "2016-01-31", None),
           ("상승장 2016-01~2018-09", "2016-01-04", "2016-01-31", "2018-09-28"), ("상승장 2019-01~2021-12", "2019-01-02", "2019-01-31", "2021-12-31"),
           ("상승장 2023-01~2024-12", "2023-01-03", "2023-01-31", "2024-12-31"), ("2018년 4분기 급락 2018-09~2019-12", "2018-09-04", "2018-09-30", "2019-12-31")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "proxy": D.get("proxy"),
           "notes": ["전체 = 5계좌 합산, 장투 = 장투 계좌 단독", "worst = 평가액/누적 원금 최저", "JEPI 상장(2020-05) 전은 S&P500 BuyWrite(^BXM) 대용",
                     "배당 재투자 가정(수정주가), 배당세·수수료 제외", "과열 2개+ 달은 현행 7:3 유지"], "rows": []}
    for name, a, b, e in win:
        ks = [k for k, d in enumerate(D["dates"]) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [x[0] for x in SCEN] else ks[0]
        end = next((k for k, d in enumerate(D["dates"]) if d >= e), len(D["dates"]) - 1) if e else len(D["dates"]) - 1
        for vn, cfg in V:
            r = run(D, i0, end=end, cfg=cfg); ltf, ltc = r["ltf"], r["ltc"]; dates = D["dates"]
            fmap = {}
            for d, v in ltf: fmap[d] = fmap.get(d, 0) - v
            cum = 0; worst = 0; lpk = 0; lmdd = 0
            for k, (v, s_, stg) in enumerate(ltc):
                cum += fmap.get(dates[i0 + k], 0)
                if cum > 0: worst = min(worst, v / cum - 1)
            cv = r["curve"]; pk = cv[0]; mdd = 0
            for x in cv: pk = max(pk, x); mdd = min(mdd, x / pk - 1)
            lt = r["A"]["longterm"]; hv = {t: round(lt.v(t, D["P"], end, D["fx"][end]) / MAN) for t in lt.u}
            row = {"window": name, "strategy": vn, "start": dates[i0], "end": dates[end],
                   "total_irr": xirr(r["flows"], dates[end], cv[-1]), "total_worst": round(min(min(x / p - 1 for x, p in zip(cv, r["prin"])), 0) * 100, 1),
                   "total_mdd": round(mdd * 100, 1), "end_man": round(cv[-1] / MAN),
                   "lt_irr": xirr(ltf, dates[end], ltc[-1][0]) if ltf else None, "lt_worst": round(worst * 100, 1), "lt_hold_man": hv}
            out["rows"].append(row); print("N2R", json.dumps(row, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(B.DATA, "n2_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def btc_study(D, y):
    """11-14 Ben: BITO 상한을 비트코인 현물 낙폭에 연동 (−50% 5 / −70% 8 / −80% 12). → data/btc_bt.json
    모형: 현행 5계좌 규칙(run)의 일별 시간가중수익률을 '나머지 포트폴리오'로 쓰고, 그 위에 BITO 칸을 얹는다.
    BITO 몫은 매달 330만 안에서 먼저 떼고(현행 규칙), 상한이 올라간 달에는 부족분을 3개월에 나눠 나머지 포트폴리오에서 옮긴다."""
    dates = D["dates"]; n = len(dates)
    btc_raw = [(r[0], r[4]) for r in y.get("BTC-USD", []) if r[4]]
    if len(btc_raw) < 500: print("BTC 데이터 없음"); return
    btc = ff(btc_raw, dates)
    k_btc0 = next(k for k in range(n) if btc[k])
    # 낙폭: 2013-12 고점(약 1,150달러)부터 누적 최고가 기준 (야후 BTC-USD는 2014-09부터)
    pk = 1150.0; dd = [None] * n
    for k in range(k_btc0, n):
        pk = max(pk, btc[k]); dd[k] = (btc[k] / pk - 1) * 100
    DRAG = 0.06 / 252   # BITO 선물 롤오버 비용 가정 연 6%
    # 실제 BITO가 있으면 같은 구간 BTC 대비 연 괴리 출력
    bito = dict((r[0], r[5]) for r in y.get("BITO", []) if r[5])
    gap_note = None
    if len(bito) > 500:
        bd = sorted(bito); a, b = bd[0], bd[-1]
        ka = next(k for k in range(n) if dates[k] >= a); kb = next((k for k in range(n) if dates[k] >= b), n - 1)
        yrs = (datetime.strptime(dates[kb], "%Y-%m-%d") - datetime.strptime(dates[ka], "%Y-%m-%d")).days / 365.25
        rb = (bito[b] / bito[a]) ** (1 / yrs) - 1; rc = (btc[kb] / btc[ka]) ** (1 / yrs) - 1
        gap_note = {"from": a, "to": b, "bito_cagr": round(rb * 100, 1), "btc_cagr": round(rc * 100, 1)}
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    CUR = {**L, "gold": 17, "normal": (0.7, 0.7), "m10": (85, 85, 30, 0), "bigcut": "stage_ma"}
    R = {"tiers": [(-80, 9), (-70, 6)], "base": 3, "trim": 2.0}
    V = [("R 추천안(확정): 3/6/9 + 차익", {**R}),
         ("K1 코어 = 월 기본 적립(12만→3만) 전부, 매도 없음 / 나머지 3/6/9+차익", {**R, "core": ("all", 0)}),
         ("K2 코어 전체 1%까지 매도 없음 / 나머지 3/6/9+차익", {**R, "core": ("pct", 1)}),
         ("K3 코어 전체 2%까지 매도 없음 / 나머지 3/6/9+차익", {**R, "core": ("pct", 2)}),
         ("c 현행 3% 고정(매수만 멈춤)", {"tiers": [], "base": 3, "trim": None}),
         ("R 비용0(현물 가정)", {**R, "drag": 0}),
         ("K1 비용0(현물 가정)", {**R, "core": ("all", 0), "drag": 0}),
         ("K2 비용0(현물 가정)", {**R, "core": ("pct", 1), "drag": 0}),
         ("0 비트코인 없음", None)]
    def idx(d): return next((k for k, x in enumerate(dates) if x >= d), n - 1)
    win = [("2014 사이클 2014-09~2017-12", "2014-09-17", "2017-12-15"), ("2018 사이클 2017-12~2021-11", "2017-12-15", "2021-11-08"),
           ("2022 사이클 2021-11~", "2021-11-08", None), ("2014-09~현재 전체", "2014-09-17", None), ("2018-01~현재", "2017-12-15", None)]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bito_vs_btc": gap_note,
           "notes": ["전체 = 5계좌 + BITO, 월 330만 (BITO 몫은 장투 적립에서 차감)", "BITO = 비트코인 현물 일간수익 − 연 6% 롤오버 비용 가정",
                     "상한 판정 = 비트코인 현물 고점 대비 낙폭(2013-12 고점 1,150달러 포함)", "상한이 오르면 부족분을 3개월 분할로 나머지 포트폴리오에서 옮김",
                     "세금(해외 ETF 양도세 22%, 250만 공제)·수수료 제외", "매수 후보 달 24만 규칙은 생략"],
           "rows": []}
    for wn, a, b in win:
        i0 = idx(a); end = idx(b) if b else n - 1
        base = run(D, i0, end=end, cfg=CUR); cv = base["curve"]; inflow = {}
        for d, v in base["flows"]: inflow[d] = inflow.get(d, 0) - v
        for vn, vc in V:
            core = 0.0; bt = 0.0; bc = 0.0; prin = 0.0; flows = []; worst = 0; pkv = 0; mdd = 0; months = 0; fill = 0.0; fill_left = 0
            maxw = 0; tr_n = 0; buy_extra = 0.0; sold = 0.0; dr = (vc.get("drag", 0.06) if vc else 0.06) / 252; ck = (vc or {}).get("core")
            for k in range(i0, end + 1):
                j = k - i0
                if j > 0:
                    prev = cv[j - 1]; add = inflow.get(dates[k], 0)
                    rc = (cv[j] - add) / prev - 1 if prev else 0
                    core *= 1 + rc
                    if btc[k] and btc[k - 1]: g = (btc[k] / btc[k - 1]) * (1 - dr); bt *= g; bc *= g
                add = inflow.get(dates[k], 0)
                if add:
                    prin += add; flows.append((dates[k], -add)); months += 1
                    if vc is None:
                        core += add
                    else:
                        tot = core + bt + bc + add; capp = vc["base"]
                        for th, cp in vc["tiers"]:
                            if dd[k] is not None and dd[k] <= th: capp = cp; break
                        cap = tot * capp / 100
                        base_amt = (12 if months <= 6 else 3) * MAN
                        to_core = 0
                        if btc[k] and ck:
                            if ck[0] == "all": to_core = base_amt
                            elif bc < tot * ck[1] / 100: to_core = min(base_amt, tot * ck[1] / 100 - bc)
                        bc += to_core
                        x = min(base_amt - to_core, max(0.0, cap - bt)) if btc[k] else 0
                        bt += x; core += add - x - to_core
                        gap = cap - bt
                        if gap > 0 and capp > vc["base"] and btc[k]:
                            if fill_left <= 0: fill = gap / 3; fill_left = 3
                            y_ = min(fill, gap, core); bt += y_; core -= y_; buy_extra += y_; fill_left -= 1
                        else:
                            fill_left = 0
                        if vc["trim"] and btc[k] and bt > cap * vc["trim"]:
                            z = bt - cap; bt -= z; core += z; sold += z; tr_n += 1
                tv = core + bt + bc
                if prin > 0: worst = min(worst, tv / prin - 1)
                pkv = max(pkv, tv); mdd = min(mdd, tv / pkv - 1) if pkv else 0
                if tv: maxw = max(maxw, (bt + bc) / tv)
            tv = core + bt + bc
            row = {"window": wn, "strategy": vn, "start": dates[i0], "end": dates[end], "irr": xirr(flows, dates[end], tv),
                   "worst": round(worst * 100, 1), "mdd": round(mdd * 100, 1), "end_man": round(tv / MAN), "prin_man": round(prin / MAN),
                   "btc_w_end": round((bt + bc) / tv * 100, 1) if tv else 0, "core_w_end": round(bc / tv * 100, 1) if tv else 0, "btc_w_max": round(maxw * 100, 1),
                   "extra_buy_man": round(buy_extra / MAN), "trim_n": tr_n, "trim_man": round(sold / MAN),
                   "btc_dd_min": round(min(x for x in dd[i0:end + 1] if x is not None), 1)}
            out["rows"].append(row); print("BTCR", json.dumps(row, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(B.DATA, "btc_core_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def gap40_study(D):
    """11-14 Ben: 40주선 하향 이격도(주봉 종가/40주선 −1)를 매수 타점으로? → data/gap40_bt.json
    1) 이벤트: 이격도가 처음 T% 이하로 내려간 주(이격도가 −3% 위로 회복하면 재무장). 이후 3·6·12개월 수익, 12개월 안 추가 최저, 그때 5년 고점 낙폭.
    2) 같은 기준으로 5년 고점 낙폭 사다리(−10/−15/−20/−25/−30/−40) 첫 도달 이벤트.
    3) 현금 풀 비교: 월 1씩 단기금리로 모으고 규칙대로 QQQ 매수(보유 유지). 사다리 / 이격도 / 둘 다 / 매달 바로 매수."""
    dates, c, dd = D["dates"], D["c"], D["dd"]; P = D["P"]["QQQ"]; rf = D["rf"]; n = len(dates)
    wk = {}
    for k in range(n):
        wk[datetime.strptime(dates[k], "%Y-%m-%d").isocalendar()[:2]] = k
    wi = [wk[x] for x in sorted(wk)]
    if datetime.strptime(dates[-1], "%Y-%m-%d").weekday() != 4: wi = wi[:-1]
    wc = [c[k] for k in wi]
    gap = [None] * len(wi)
    for j in range(39, len(wi)):
        gap[j] = (wc[j] / (sum(wc[j - 39:j + 1]) / 40) - 1) * 100
    gap_d = [None] * n; j = 0   # 일별로 '직전 마감 주' 이격도
    for k in range(n):
        while j + 1 < len(wi) and wi[j + 1] <= k: j += 1
        gap_d[k] = gap[j] if wi[j] <= k else None

    def fwd(k, days):
        k2 = min(n - 1, k + days)
        return round((P[k2] / P[k] - 1) * 100, 1) if k + days < n else None

    def ev_stats(evs):
        out = {"n": len(evs)}
        for key in ("r3", "r6", "r12", "low12"):
            v = [e[key] for e in evs if e[key] is not None]
            out[key + "_avg"] = round(sum(v) / len(v), 1) if v else None
            out[key + "_med"] = round(sorted(v)[len(v) // 2], 1) if v else None
            if key in ("r6", "r12"): out[key + "_win"] = round(sum(1 for x in v if x > 0) / len(v) * 100) if v else None
        lv = [e["low12"] for e in evs if e["low12"] is not None]
        out["low12_le_-10"] = sum(1 for x in lv if x <= -10); out["low12_le_-20"] = sum(1 for x in lv if x <= -20)
        return out

    def mk(k):
        lo = min(c[k:min(n, k + 252)])
        return {"date": dates[k], "gap": round(gap_d[k], 1) if gap_d[k] is not None else None, "dd5y": round(dd[k], 1),
                "r3": fwd(k, 63), "r6": fwd(k, 126), "r12": fwd(k, 252), "low12": round((lo / c[k] - 1) * 100, 1)}

    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "from": dates[wi[39]], "gap_now": round(gap[-1], 1),
           "notes": ["이격도 = QQQ 주봉 종가 / 40주 이동평균 − 1, 주 마감 기준", "이벤트 = 처음 T 이하로 내려간 주(−3% 위로 회복하면 다시 셈)",
                     "수익은 QQQ 배당 포함, low12 = 이후 12개월 안 최저 종가까지 추가 하락", "세금·수수료 제외"],
           "gap": {}, "ladder": {}, "base": {}, "pool": []}
    base = [mk(k) for k in range(wi[39], n - 1, 5)]
    out["base"] = ev_stats(base)
    for T in (-5, -10, -15, -20, -25, -30):
        evs = []; armed = True
        for k in range(n):
            g = gap_d[k]
            if g is None: continue
            if g > -3: armed = True
            elif armed and g <= T and (k == 0 or gap_d[k - 1] != g):
                evs.append(mk(k)); armed = False
        out["gap"][str(T)] = {**ev_stats(evs), "events": evs}
    for T in (-10, -15, -20, -25, -30, -40):
        evs = []; armed = True
        for k in range(n):
            if dd[k] > -3: armed = True
            elif armed and dd[k] <= T:
                evs.append(mk(k)); armed = False
        out["ladder"][str(T)] = {**ev_stats(evs), "events": evs}
    # 현금 풀 비교
    LAD = [(-25, 5), (-30, 10), (-35, 15), (-40, 15), (-50, 25), (-60, 30)]   # 현금 계좌 사다리(모은 돈 %)
    GAP = [(-10, 25), (-15, 25), (-20, 25), (-25, 25)]
    def pool(mode, k0):
        cash = 0.0; sh = 0.0; flows = []; last_m = None; ld = set(); gd = set(); spent_l = 0.0; spent_g = 0.0; vals = []
        for k in range(k0, n):
            if k > k0: cash *= 1 + rf[k - 1] / 252
            m = dates[k][:7]
            if m != last_m and int(dates[k][8:]) >= 1:
                last_m = m; flows.append((dates[k], -1.0))
                if mode == "dca": sh += 1.0 / P[k]
                else: cash += 1.0
            if mode in ("lad", "both"):
                if dd[k] > -3: ld = set()
                for lv, pc in LAD:
                    if dd[k] <= lv and lv not in ld:
                        rem = 100 - sum(p for l2, p in LAD if l2 in ld); x = cash * pc / rem if rem > 0 else cash
                        sh += x / P[k]; cash -= x; ld.add(lv)
            if mode in ("gap", "both") and gap_d[k] is not None:
                if gap_d[k] > -3: gd = set()
                for lv, pc in GAP:
                    if gap_d[k] <= lv and lv not in gd:
                        rem = 100 - sum(p for l2, p in GAP if l2 in gd); x = cash * pc / rem if rem > 0 else cash
                        sh += x / P[k]; cash -= x; gd.add(lv)
            vals.append(cash + sh * P[k])
        pk = 0; mdd = 0
        for v in vals: pk = max(pk, v); mdd = min(mdd, v / pk - 1)
        fv = cash + sh * P[n - 1]
        return {"irr": xirr(flows, dates[n - 1], fv), "end": round(fv, 1), "cash_share_end": round(cash / fv * 100, 1), "mdd": round(mdd * 100, 1)}
    for wn, a in (("1999-12~", "1999-12-01"), ("2007-10~", "2007-10-01"), ("2010~", "2010-01-04"), ("2016~", "2016-01-04"), ("2020-02~", "2020-02-19"), ("2021-11~", "2021-11-19")):
        k0 = next(k for k in range(n) if dates[k] >= a)
        for mode, lab in (("dca", "매달 바로 QQQ"), ("lad", "낙폭 사다리(현금 계좌 규칙)"), ("gap", "이격도 −10/−15/−20/−25에 25%씩"), ("both", "사다리 + 이격도")):
            r = pool(mode, k0); out["pool"].append({"window": wn, "mode": lab, **r}); print("GAPP", wn, lab, r, flush=True)
    for T, v in out["gap"].items(): print("GAP", T, {k: x for k, x in v.items() if k != "events"}, flush=True)
    for T, v in out["ladder"].items(): print("LAD", T, {k: x for k, x in v.items() if k != "events"}, flush=True)
    json.dump(out, open(os.path.join(B.DATA, "gap40_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def gapswing_study(D):
    """11-14 Ben: 40주 데드 + 하향 이격도 큼 → 장투 적립 일부를 스윙(약세장 반등 단타), 골든이면 장투 복귀. → data/gapswing_bt.json"""
    dates, P = D["dates"], D["P"]; n = len(dates); c = D["c"]
    info = w40_prep(D)
    wk = {}
    for k in range(n): wk[datetime.strptime(dates[k], "%Y-%m-%d").isocalendar()[:2]] = k
    wi = [wk[x] for x in sorted(wk)]
    gap = [None] * len(wi)
    for j in range(39, len(wi)):
        if j < len(wi) - 1 or datetime.strptime(dates[wi[j]], "%Y-%m-%d").weekday() == 4:
            gap[j] = (c[wi[j]] / (sum(c[wi[x]] for x in range(j - 39, j + 1)) / 40) - 1) * 100
    gd = [None] * n; j = 0
    for k in range(n):
        while j + 1 < len(wi) and wi[j + 1] <= k and gap[j + 1] is not None: j += 1
        gd[k] = gap[j] if wi[j] <= k else None
    D["gap40"] = gd
    L = {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}
    CUR = {**L, "gold": 17, "normal": (0.7, 0.7), "m10": (85, 85, 30, 0), "bigcut": "stage_ma"}
    V = [("A 지금 규칙", CUR),
         ("S1 데드+이격 −10%↓: 적립 25% → 스윙, QLD 반등 단타", {**CUR, "gap_gate": -10, "sw40": 0.25}),
         ("S2 데드+이격 −10%↓: 적립 50% → 스윙, QLD", {**CUR, "gap_gate": -10, "sw40": 0.5}),
         ("S3 데드+이격 −15%↓: 적립 50% → 스윙, QLD", {**CUR, "gap_gate": -15, "sw40": 0.5}),
         ("S4 데드+이격 −10%↓: 적립 50% → 스윙, QQQ(1배)", {**CUR, "gap_gate": -10, "sw40": 0.5, "sw40_inst": "QQQ"}),
         ("S5 데드+이격 −10%↓: 적립 50% → 스윙, TQQQ", {**CUR, "gap_gate": -10, "sw40": 0.5, "sw40_inst": "TQQQ"})]
    win = [(nm, a, b, None) for nm, a, b in SCEN] + [("2010~", "2010-01-04", "2010-01-31", None), ("2016~", "2016-01-04", "2016-01-31", None),
           ("상승장 2019-01~2021-12", "2019-01-02", "2019-01-31", "2021-12-31"), ("2018년 4분기 급락 2018-09~2019-12", "2018-09-04", "2018-09-30", "2019-12-31")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "notes": ["전체 = 5계좌 합산, 장투 = 장투 계좌 + 스윙으로 돌린 몫 제외", "스윙 진입: 스윙 모드 중 QQQ 일봉 RSI ≤ 30이면 계좌 25%씩(최대 4개, 5거래일 간격)",
                     "청산: +5% 절반, +10% 나머지, −10% 손절, 10거래일", "다 정리하고 이익이면 이익 50% 장투로, 골든 크로스 때 남은 현금 전부 장투로", "세금·수수료 제외"], "rows": []}
    for name, a, b, e in win:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k]) if name in [x[0] for x in SCEN] else ks[0]
        end = next((k for k, d in enumerate(dates) if d >= e), n - 1) if e else n - 1
        for vn, cfg in V:
            if "GOLD" not in P: break
            r = run(D, i0, end=end, cfg=cfg); ltf, ltc = r["ltf"], r["ltc"]
            cv = r["curve"]; pk = cv[0]; mdd = 0
            for x in cv: pk = max(pk, x); mdd = min(mdd, x / pk - 1)
            tr = r["s4_tr"]
            row = {"window": name, "strategy": vn, "start": dates[i0], "end": dates[end],
                   "total_irr": xirr(r["flows"], dates[end], cv[-1]), "total_worst": round(min(min(x / p - 1 for x, p in zip(cv, r["prin"])), 0) * 100, 1),
                   "total_mdd": round(mdd * 100, 1), "end_man": round(cv[-1] / MAN), "lt_irr": xirr(ltf, dates[end], ltc[-1][0]) if ltf else None,
                   "trades": len(tr), "win_pct": round(sum(1 for x in tr if x > 0) / len(tr) * 100) if tr else None,
                   "avg_trade_pct": round(sum(tr) / len(tr), 2) if tr else None, "stops": r["s4_stop"], "diverted_man": round(r["s4_div"]),
                   "sw_end_man": round(r["A"]["sw40"].val(P, end, D["fx"][end]) / MAN)}
            out["rows"].append(row); print("GSR", json.dumps(row, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(B.DATA, "gapswing_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def swing_study(D):
    """단기 급락 스윙(짧게 사고 나오기) 규칙 비교 → data/swing_bt.json. 스윙 계좌 단독, 쉬는 돈은 SGOV"""
    dates, P, c, rsi = D["dates"], D["P"], D["c"], D["rsi"]
    n = len(dates)
    def bbl(i):
        if i < 19: return None
        w = c[i - 19:i + 1]; mu = sum(w) / 20; sd = (sum((x - mu) ** 2 for x in w) / 20) ** 0.5
        return mu - 2 * sd
    def ret(i, k): return (c[i] / c[i - k] - 1) * 100 if i >= k else 0
    SIG = {
        "dip2": ("QQQ 하루 −2%↓ + RSI ≤ 40", lambda i: ret(i, 1) <= -2 and (rsi[i] or 99) <= 40),
        "rsi30": ("QQQ RSI ≤ 30", lambda i: (rsi[i] or 99) <= 30),
        "bb": ("QQQ 볼린저 하단 이탈 + RSI ≤ 35", lambda i: bbl(i) is not None and c[i] < bbl(i) and (rsi[i] or 99) <= 35),
        "d3": ("QQQ 3일 −5%↓", lambda i: ret(i, 3) <= -5),
        "d3r": ("QQQ 3일 −5%↓ + RSI ≤ 35", lambda i: ret(i, 3) <= -5 and (rsi[i] or 99) <= 35),
    }
    EXIT = {
        "tp": ("+8% 절반·+15% 나머지 (손절·기간 없음 = 지금 규칙)", dict(tp1=8, tp2=15, stop=None, days=None, mr=False)),
        "tp_s_t": ("+8% 절반·+15% 나머지, −12% 손절, 20거래일 청산", dict(tp1=8, tp2=15, stop=-12, days=20, mr=False)),
        "fast": ("+5% 절반·+10% 나머지, −10% 손절, 10거래일 청산", dict(tp1=5, tp2=10, stop=-10, days=10, mr=False)),
        "mr": ("RSI ≥ 50 또는 20일선 회복 시 전량, −12% 손절, 15거래일 청산", dict(tp1=None, tp2=None, stop=-12, days=15, mr=True)),
        "mr_tp": ("+8% 절반 → 나머지는 RSI ≥ 55·20일선 회복, −12% 손절, 20거래일", dict(tp1=8, tp2=None, stop=-12, days=20, mr=True)),
    }
    def sim(i0, i1, inst, sig, ex, unit=1 / 3, lots=3, gap=5):
        cash = 1.0; pos = []   # [qty, entry_px, entry_i, half_done]
        f = SIG[sig][1]; e = EXIT[ex][1]; last = -99; trades = []; curve = []
        sg = P["SGOV"]
        for i in range(i0, i1 + 1):
            if i > i0: cash *= sg[i] / sg[i - 1]
            px = P[inst][i]
            m20 = sum(c[i - 19:i + 1]) / 20 if i >= 19 else None
            keep = []
            for q, ep, ei, hd in pos:
                g = (px / ep - 1) * 100; held = i - ei
                out = 0
                if e["stop"] is not None and g <= e["stop"]: out = 1
                elif e["days"] is not None and held >= e["days"]: out = 1
                elif e["tp2"] is not None and g >= e["tp2"]: out = 1
                elif e["mr"] and (hd or e["tp1"] is None) and ((rsi[i] or 0) >= (55 if e["tp1"] else 50) or (m20 and c[i] > m20)) and held >= 2: out = 1
                if not out and e["tp1"] is not None and not hd and g >= e["tp1"]:
                    cash += q / 2 * px; q /= 2; hd = True
                if out:
                    cash += q * px; trades.append((ep, px, held, g))
                else: keep.append([q, ep, ei, hd])
            pos = keep
            tot = cash + sum(p[0] * px for p in pos)
            if f(i) and len(pos) < lots and i - last >= gap:
                amt = min(cash, tot * unit)
                if amt > 0: cash -= amt; pos.append([amt / px, px, i, False]); last = i
            curve.append(cash + sum(p[0] * px for p in pos))
        yrs = (i1 - i0) / 252
        cagr = (curve[-1] ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
        pk = 0; mdd = 0
        for v in curve: pk = max(pk, v); mdd = min(mdd, v / pk - 1)
        exp = sum(1 for k in range(len(curve)) if True) and None
        wins = [t for t in trades if t[1] > t[0]]
        return {"cagr": round(cagr, 2), "mdd": round(mdd * 100, 1), "trades": len(trades), "win": round(len(wins) / len(trades) * 100) if trades else None,
                "avg_hold": round(sum(t[2] for t in trades) / len(trades), 1) if trades else None,
                "avg_ret": round(sum(t[3] for t in trades) / len(trades), 1) if trades else None,
                "worst": round(min(t[3] for t in trades), 1) if trades else None}
    def bh(i0, i1, t):
        yrs = (i1 - i0) / 252; v = [P[t][k] / P[t][i0] for k in range(i0, i1 + 1)]
        pk = 0; mdd = 0
        for x in v: pk = max(pk, x); mdd = min(mdd, x / pk - 1)
        return {"cagr": round((v[-1] ** (1 / yrs) - 1) * 100, 2), "mdd": round(mdd * 100, 1)}
    def idx(d): return next((k for k, x in enumerate(dates) if x >= d), n - 1)
    W = [("2000~", "2000-01-03", None), ("2008~", "2008-01-02", None), ("2016~", "2016-01-04", None), ("2020~", "2020-01-02", None),
         ("닷컴 2000-03~2002-12", "2000-03-01", "2002-12-31"), ("금융위기 2007-10~2009-06", "2007-10-01", "2009-06-30"),
         ("2022", "2022-01-03", "2022-12-30"), ("2025-02~06", "2025-02-03", "2025-06-30")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "notes": ["스윙 계좌 단독, 1회 계좌 1/3, 최대 3묶음, 5거래일 간격", "쉬는 돈은 SGOV(단기채 금리)", "QLD·TQQQ 상장 전은 QQQ 일간 2·3배 합성", "세금·수수료 제외"],
           "signals": {k: v[0] for k, v in SIG.items()}, "exits": {k: v[0] for k, v in EXIT.items()}, "rows": [], "bench": []}
    for wn, a, b in W:
        i0 = idx(a); i1 = idx(b) if b else n - 1
        out["bench"].append({"window": wn, "SGOV": bh(i0, i1, "SGOV"), "QQQ": bh(i0, i1, "QQQ"), "QLD": bh(i0, i1, "QLD")})
        for inst in ("QLD", "TQQQ"):
            for sk in SIG:
                for ek in EXIT:
                    r = sim(i0, i1, inst, sk, ek)
                    out["rows"].append({"window": wn, "inst": inst, "sig": sk, "exit": ek, **r})
        print("SWING", wn, flush=True)
    json.dump(out, open(os.path.join(B.DATA, "swing_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def swing_study2(D):
    """Ben 11-14 스윙 설계: 배수가 클수록 더 깊은 낙폭에서 진입, 신호 있는 달만 월 적립 일부 배정, 수익권이면 이익 일부 장투 이관 → data/swing2_bt.json"""
    dates, P = D["dates"], D["P"]; n = len(dates)
    BT = [t for t in ("NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA") if t in P]
    INST = [(t, 1) for t in BT] + [("QLD", 2), ("TQQQ", 3), ("SOXL", 3)]
    R = {t: B.rsi_series([x if x is not None else 0 for x in P[t]]) for t, _ in INST}
    def dd52(t, i):
        w = [x for x in P[t][max(0, i - 251):i + 1] if x is not None]
        return (P[t][i] / max(w) - 1) * 100 if w and P[t][i] is not None else 0
    DDS = {"A": {1: -25, 2: -30, 3: -40}, "B": {1: -30, 2: -40, 3: -55}, "C": {1: -35, 2: -50, 3: -65}}
    EX = {"fast": (5, 10, -10, 10), "mid": (8, 15, -12, 20), "wide": (15, 30, -20, 40)}
    def sim(i0, i1, dk, ek, monthly, unit=0.25, maxpos=4, xfer=0.5):
        cash = 400.0; paid = 400.0; flows = [(dates[i0], -400.0)]; pos = []; last = {}; trades = []; curve = []; moved = 0.0; lastm = None; sig_recent = -999
        tp1, tp2, st, days = EX[ek]
        for i in range(i0, i1 + 1):
            if i > i0: cash *= P["SGOV"][i] / P["SGOV"][i - 1]
            d = dates[i]
            # 월 배정: 최근 20거래일 안에 진입 신호가 있었던 달만
            if monthly and d[:7] != lastm and int(d[8:]) >= 25:
                lastm = d[:7]
                if i - sig_recent <= 20: cash += monthly; paid += monthly; flows.append((d, -monthly))
            keep = []; closed = False
            for p in pos:
                t = p["t"]; px = P[t][i]; g = (px / p["ep"] - 1) * 100; held = i - p["i"]
                if not p["h"] and g >= tp1: cash += p["q"] / 2 * px; p["q"] /= 2; p["h"] = True
                if g <= st or held >= days or g >= tp2:
                    cash += p["q"] * px; trades.append((g, held, p["m"])); closed = True
                else: keep.append(p)
            pos = keep
            val = cash + sum(p["q"] * P[p["t"]][i] for p in pos)
            # 수익권이면(납입 원금 대비 +) 포지션이 없을 때 이익의 xfer만큼 장투로 이관
            if closed and not pos and val > paid and xfer:
                out = (val - paid) * xfer; cash -= out; moved += out; flows.append((d, out)); val -= out
            for t, m in INST:
                if P[t][i] is None or R[t][i] is None: continue
                if dd52(t, i) <= DDS[dk][m] and R[t][i] <= 30:
                    sig_recent = i
                    if len(pos) < maxpos and i - last.get(t, -99) >= 5 and sum(1 for p in pos if p["t"] == t) < 2:
                        amt = min(cash, val * unit)
                        if amt > 1: cash -= amt; pos.append({"t": t, "m": m, "q": amt / P[t][i], "ep": P[t][i], "i": i, "h": False}); last[t] = i
            curve.append(cash + sum(p["q"] * P[p["t"]][i] for p in pos))
        pk = 0; mdd = 0
        for v in curve: pk = max(pk, v); mdd = min(mdd, v / pk - 1)
        irr = xirr(flows, dates[i1], curve[-1])
        # 같은 돈을 같은 날 QQQ에 넣었을 때 (이관분은 같은 날 회수)
        q = 0.0; qf = []
        for fd, fv in flows:
            k = dates.index(fd); q += -fv / P["QQQ"][k]; qf.append((fd, fv))
        qirr = xirr(qf, dates[i1], q * P["QQQ"][i1])
        bym = {}
        for g, h, m in trades: bym.setdefault(m, []).append(g)
        return {"irr": irr, "qqq_same_flows_irr": qirr, "mdd": round(mdd * 100, 1), "trades": len(trades), "win": round(sum(1 for t in trades if t[0] > 0) / len(trades) * 100) if trades else None,
                "avg_hold": round(sum(t[1] for t in trades) / len(trades), 1) if trades else None, "worst": round(min(t[0] for t in trades), 1) if trades else None,
                "paid": round(paid), "moved_to_lt": round(moved), "end": round(curve[-1]), "by_mult": {str(m): [len(v), round(sum(v) / len(v), 1)] for m, v in bym.items()}}
    def idx(d): return next((k for k, x in enumerate(dates) if x >= d), n - 1)
    W = [("2000~", "2000-01-03", None), ("2010~", "2010-01-04", None), ("2016~", "2016-01-04", None),
         ("닷컴 2000-03~2002-12", "2000-03-01", "2002-12-31"), ("금융위기 2007-10~2009-06", "2007-10-01", "2009-06-30"), ("2022", "2022-01-03", "2022-12-30"), ("2025-02~06", "2025-02-03", "2025-06-30")]
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bigtech": BT,
           "notes": ["시작 400만, 1회 계좌 25%, 동시 최대 4개(종목당 2개), 같은 종목 5거래일 간격", "진입: 1년 고점 대비 낙폭(배수별 기준) + 그 종목 RSI ≤ 30",
                     "월 배정: 최근 20거래일 안에 신호가 있던 달만 적립일에 배정", "이관: 포지션을 다 정리했고 원금 대비 이익이면 이익의 50%를 장투로",
                     "SOXL은 SOXX 3배 합성, 빅테크는 상장 이후만", "세금·수수료 제외"],
           "dd_sets": DDS, "exits": {k: f"+{v[0]}% 절반·+{v[1]}% 나머지, {v[2]}% 손절, {v[3]}거래일" for k, v in EX.items()}, "rows": []}
    for wn, a, b in W:
        i0 = idx(a); i1 = idx(b) if b else n - 1
        for dk in DDS:
            for ek in EX:
                for mo in (0, 20, 40):
                    r = sim(i0, i1, dk, ek, mo)
                    out["rows"].append({"window": wn, "dd": dk, "exit": ek, "monthly": mo, **r})
        print("SWING2", wn, flush=True)
    json.dump(out, open(os.path.join(B.DATA, "swing2_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    y, f = load()
    D = prep(y, f)
    dates = D["dates"]
    if os.environ.get("ONLY_GSW"):
        gapswing_study(D); print("ok"); return
    if os.environ.get("ONLY_GAP"):
        gap40_study(D); print("ok"); return
    if os.environ.get("ONLY_BTC"):
        btc_study(D, y); print("ok"); return
    if os.environ.get("ONLY_N2"):
        n2_study(D); print("ok"); return
    if os.environ.get("ONLY_W40"):
        w40_study(D); print("ok"); return
    if os.environ.get("ONLY_MARGIN"):
        margin_study(D); print("ok"); return
    if os.environ.get("ONLY_DIV"):
        div_study(D); print("ok"); return
    if os.environ.get("ONLY_SWING"):
        swing_study2(D); swing_study(D); print("ok"); return
    if os.environ.get("ONLY_PARKV"):
        park_verify(D); print("ok"); return
    if os.environ.get("ONLY_PARK"):
        park_study(D); print("ok"); return
    if os.environ.get("ONLY_DDWIN"):
        ddwin_study(D); print("ok"); return
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
        ("H 배당 15%(QQQM5·SPYM25) + 과열 시 배당, 하락 시 교체", {"div": (5, 25), "div_sell": True}),
        ("I = H에서 교체 매도 없음", {"div": (5, 25)}),
        ("J 배당 20%(QQQM10·SPYM30) + 과열·교체", {"div": (10, 30), "div_sell": True}),
        ("K 최종: 배당 15% SCHD·JEPI·DIVO·JEPQ 중 싼 것 + 과열·교체", {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"]}),
        ("L 최종 + 반등 가속 B", {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True}),
        ("M = L + 현금 적립 절반(나머지 1배 지수 즉시)", {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True, "ammo_frac": 0.5}),
        ("N = L + 현금 적립 없음(전부 1배 지수 즉시)", {"div": (5, 25), "div_sell": True, "div_pool": ["SCHD", "JEPI", "DIVO", "JEPQ"], "trigger": "ma200", "frac": 0.5, "mix": {"QLD": 100}, "stop": True, "ammo_frac": 0.0}),
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
            if vname.startswith("L "):   # 채택 규칙의 월별 자산 곡선(그래프용, 만원)
                cv = {"dates": [], "strat": [], "qqq": [], "spy": [], "prin": []}; lastm = None
                for k in range(len(r["curve"])):
                    d = dates[i0 + k]
                    if d[:7] != lastm or k == len(r["curve"]) - 1:
                        lastm = d[:7]; cv["dates"].append(d)
                        for key, arr in (("strat", r["curve"]), ("qqq", bq), ("spy", bs), ("prin", r["prin"])):
                            cv[key].append(round(arr[k] / MAN))
                out.setdefault("curves", {})[name] = cv
            out["variants"].append({"scenario": name, "variant": vname, "start": dates[i0],
                                    "worst": m["underwater"].get("worst_vs_principal_pct"), "uw_months": m["underwater"].get("months"),
                                    "mdd5": m["mdd_5y"][0], "y1": (m["horizon"]["1y"] or {}).get("ret_pct"), "y3": (m["horizon"]["3y"] or {}).get("ret_pct"),
                                    "y5": (m["horizon"]["5y"] or {}).get("ret_pct"), "end": m["horizon"]["end"]["ret_pct"], "irr_end": m["horizon"]["end"]["irr"],
                                    "events": [e for e in r["log"] if "반등" in e[1]][:12]})
            print(name, vname, out["variants"][-1]["worst"], out["variants"][-1]["uw_months"], out["variants"][-1]["y3"], out["variants"][-1]["y5"], out["variants"][-1]["end"], flush=True)
    out["unified"] = []
    for name, a, b in SCEN:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k])
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        for key, label in (("CUR", "기존 5계좌 규칙"), ("U0", "3분할 고정 리밸런싱(신호 없음)"), ("U1", "통합 4종목 신호 리밸런싱"), ("U2", "통합 4종목 공격형"), ("U0S", "3분할 고정 SCHD판"), ("U1S", "통합 4종목 SCHD판"), ("QP", "QQQ·SPY 반반 고정"), ("QS", "QQQ·SCHD 반반 고정")):
            r = run(D, i0) if key == "CUR" else run_unified(D, i0, key)
            m = metrics(D, r, bq, bs)
            h = m["horizon"]
            row = {"scenario": name, "strategy": label, "start": dates[i0],
                   "worst": m["underwater"].get("worst_vs_principal_pct"), "uw_months": m["underwater"].get("months"), "uw": m["underwater"],
                   "mdd5": m["mdd_5y"][0], "y1": (h["1y"] or {}).get("ret_pct"), "y3": (h["3y"] or {}).get("ret_pct"),
                   "y5": (h["5y"] or {}).get("ret_pct"), "y10": (h["10y"] or {}).get("ret_pct"), "end": h["end"]["ret_pct"], "irr_end": h["end"]["irr"],
                   "v3_man": (h["3y"] or {}).get("value_man"), "v5_man": (h["5y"] or {}).get("value_man"), "end_man": h["end"]["value_man"],
                   "trades": r.get("trades"), "events": r["log"][:10],
                   "qqq": {"worst": m["qqq_all_underwater"].get("worst_vs_principal_pct"), "uw": m["qqq_all_underwater"].get("months"), "y3": (h["3y"] or {}).get("qqq_all_ret_pct"), "y5": (h["5y"] or {}).get("qqq_all_ret_pct"), "end": h["end"]["qqq_all_ret_pct"]},
                   "spy": {"worst": m["spy_all_underwater"].get("worst_vs_principal_pct"), "uw": m["spy_all_underwater"].get("months"), "y3": (h["3y"] or {}).get("spy_all_ret_pct"), "y5": (h["5y"] or {}).get("spy_all_ret_pct"), "end": h["end"]["spy_all_ret_pct"]}}
            out["unified"].append(row)
            print("UNI", name, label, row["worst"], row["uw_months"], row["y3"], row["y5"], row["end"], row["irr_end"], flush=True)
    out["simple"] = []
    SIMPLE = [("S1 S&P500 적립 + 현금 6단계", {"SPY": 100}, True), ("S2 S&P500 60·QQQ 40 적립 + 현금 6단계", {"SPY": 60, "QQQ": 40}, True),
              ("S3 S&P500만 (현금 몫도 적립, IRP 70%)", {"SPY": 100}, False), ("S4 S&P500 60·QQQ 40만 (IRP 70%)", {"SPY": 60, "QQQ": 40}, False),
              ("S5 QQQ 100 + 현금 6단계", {"QQQ": 100}, True), ("S6 S&P500 50·QQQ 50 + 현금 6단계", {"SPY": 50, "QQQ": 50}, True),
              ("S7 S&P500 40·QQQ 40·배당 20 + 현금 6단계", {"SPY": 40, "QQQ": 40, "SCHD": 20}, True),
              ("S8 S&P500 30·QQQ 50·QLD 20 고정 + 현금 6단계", {"SPY": 30, "QQQ": 50, "QLD": 20}, True),
              ("S9 S&P500 40·QQQ 40·QLD 20 고정 + 현금 6단계", {"SPY": 40, "QQQ": 40, "QLD": 20}, True)]
    for name, a, b in SCEN:
        ks = [k for k, d in enumerate(dates) if a <= d <= b]
        if not ks: continue
        i0 = max(ks, key=lambda k: D["c"][k])
        bq = bench(D, i0, "QQQ"); bs = bench(D, i0, "SPY")
        LAD = [(-30, {"SPY": 20, "QQQ": 20, "QLD": 60}), (-20, {"SPY": 30, "QQQ": 30, "QLD": 40}), (-10, {"SPY": 40, "QQQ": 40, "QLD": 20})]
        BEN = [(-30, {"QQQ": 40, "QLD": 60}), (-20, {"SPY": 10, "QQQ": 50, "QLD": 40}), (-15, {"SCHD": 10, "SPY": 20, "QQQ": 50, "QLD": 20}), (-10, {"SCHD": 20, "SPY": 30, "QQQ": 40, "QLD": 10})]
        BEN_M = {"SCHD": 40, "SPY": 40, "QQQ": 20}
        EXTRA = [("R1 S&P500 50·QQQ 50 + 하락 시 QLD 사다리(-10/-20/-30%→20/40/60) + 현금 6단계", {"SPY": 50, "QQQ": 50}, True, LAD, False, False),
                 ("P1 배당40·SPY40·QQQ20 + 하락 단계별 QQQ·QLD (보유 유지) + 현금 6단계", BEN_M, True, BEN, False, True),
                 ("P2 = P1 + 전고점 회복 시 QLD→QQQ", BEN_M, True, BEN, True, True),
                 ("P0 배당40·SPY40·QQQ20 고정 + 현금 6단계", BEN_M, True, None, False, False)]
        for sname, mix, ammo, *lad in [x + (None, False, False) for x in SIMPLE] + EXTRA:
            r = run_simple(D, i0, mix, ammo, ladder=lad[0], delever=lad[1], lad_pension=lad[2])
            m = metrics(D, r, bq, bs); h = m["horizon"]
            out["simple"].append({"scenario": name, "strategy": sname, "start": dates[i0], "worst": m["underwater"].get("worst_vs_principal_pct"),
                                  "uw_months": m["underwater"].get("months"), "mdd5": m["mdd_5y"][0], "y3": (h["3y"] or {}).get("ret_pct"),
                                  "y5": (h["5y"] or {}).get("ret_pct"), "end": h["end"]["ret_pct"], "irr_end": h["end"]["irr"], "events": r["log"][:12]})
            print("SIMPLE", name, sname, out["simple"][-1]["worst"], out["simple"][-1]["uw_months"], out["simple"][-1]["irr_end"], flush=True)
    json.dump(out, open(os.path.join(B.DATA, "portfolio_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ok")


if __name__ == "__main__":
    main()
