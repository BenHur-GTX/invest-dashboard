#!/usr/bin/env python3
"""시세·거시 데이터 수집 + 지표 계산 + 백테스트 → data/market.json, data/backtest.json

GitHub Actions에서 실행한다 (표준 라이브러리만 사용).
데이터: Yahoo Finance chart API(15분 지연), Naver 차트(국내 ETF), FRED fredgraph.csv(키 불필요),
CNN 공포탐욕(비공식, 실패해도 무시).
"""
import csv, io, json, math, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

# (심볼, 표시명, 그룹, 통화, 소스)
SYMBOLS = [
    ("QQQ", "나스닥100 (QQQ)", "지수", "USD", "y"),
    ("^IXIC", "나스닥 종합", "지수", "USD", "y"),
    ("^GSPC", "S&P 500", "지수", "USD", "y"),
    ("^VIX", "VIX", "지수", "USD", "y"),
    ("^KS11", "코스피", "지수", "KRW", "y"),
    ("KRW=X", "원/달러", "지수", "KRW", "y"),
    ("QQQM", "QQQM", "1배 지수", "USD", "y"),
    ("SPYM", "SPYM", "1배 지수", "USD", "y"),
    ("MGK", "MGK", "1배 지수", "USD", "y"),
    ("SOXX", "SOXX (반도체)", "섹터", "USD", "y"),
    ("SMH", "SMH (반도체)", "섹터", "USD", "y"),
    ("XLK", "XLK (기술)", "섹터", "USD", "y"),
    ("QLD", "QLD (2배)", "레버리지", "USD", "y"),
    ("TQQQ", "TQQQ (3배)", "레버리지", "USD", "y"),
    ("SOXL", "SOXL (3배)", "레버리지", "USD", "y"),
    ("SCHD", "SCHD", "배당", "USD", "y"),
    ("JEPI", "JEPI", "배당", "USD", "y"),
    ("JEPQ", "JEPQ", "배당", "USD", "y"),
    ("DIVO", "DIVO", "배당", "USD", "y"),
    ("FDVV", "FDVV", "배당", "USD", "y"),
    ("VIG", "VIG", "배당", "USD", "y"),
    ("DGRO", "DGRO", "배당", "USD", "y"),
    ("O", "리얼티인컴 O", "배당", "USD", "y"),
    ("MO", "알트리아 MO", "배당", "USD", "y"),
    ("SGOV", "SGOV", "현금·채권", "USD", "y"),
    ("TLT", "TLT", "현금·채권", "USD", "y"),
    ("1489.T", "도쿄 1489", "기타", "JPY", "y"),
    ("MAGS", "MAGS", "빅테크", "USD", "y"),
    ("NVDA", "엔비디아", "빅테크", "USD", "y"),
    ("AAPL", "애플", "빅테크", "USD", "y"),
    ("MSFT", "마이크로소프트", "빅테크", "USD", "y"),
    ("AMZN", "아마존", "빅테크", "USD", "y"),
    ("GOOGL", "알파벳", "빅테크", "USD", "y"),
    ("META", "메타", "빅테크", "USD", "y"),
    ("AVGO", "브로드컴", "빅테크", "USD", "y"),
    ("TSLA", "테슬라", "빅테크", "USD", "y"),
    ("BRK-B", "버크셔", "빅테크", "USD", "y"),
    ("TSM", "TSMC", "빅테크", "USD", "y"),
    # 국내 상장 (연금·IRP)
    ("069500", "KODEX 200", "국내", "KRW", "n"),
    ("360750", "TIGER 미국S&P500", "국내", "KRW", "n"),
    ("426030", "TIME 미국나스닥100액티브", "국내", "KRW", "n"),
    ("0048J0", "KODEX 미국머니마켓액티브", "국내", "KRW", "n"),
    ("0046A0", "TIGER 미국초단기국채", "국내", "KRW", "n"),
    ("0137W0", "KIWOOM 미국S&P500&GOLD", "국내", "KRW", "n"),
]

FRED = {
    "hy": "BAMLH0A0HYM2", "t10y2y": "T10Y2Y", "dgs2": "DGS2", "fedu": "DFEDTARU",
    "sahm": "SAHMREALTIME", "unrate": "UNRATE", "icsa": "ICSA",
    "walcl": "WALCL", "tga": "WTREGEN", "rrp": "RRPONTSYD", "sofr": "SOFR", "iorb": "IORB",
    "vix": "VIXCLS",
}


def http_get(url, tries=2, timeout=20, headers=None):
    last = None
    for i in range(tries):
        try:
            h = {"User-Agent": UA, "Accept": "*/*"}
            h.update(headers or {})
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


# ---------- 소스 ----------
def yahoo(sym, rng="10y"):
    """[(date, open, high, low, close, adjclose)]"""
    q = urllib.request.quote(sym)
    for host in ("query1", "query2"):
        try:
            # range=max는 일봉 대신 월봉을 돌려주므로 period1/period2로 요청
            p2 = int(time.time()) + 86400
            p1 = 0 if rng == "max" else p2 - int(365.25 * 86400 * int(rng.rstrip("y")))
            txt = http_get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?period1={p1}&period2={p2}&interval=1d&includeAdjustedClose=true")
            j = json.loads(txt)["chart"]["result"][0]
            ts = j["timestamp"]; qu = j["indicators"]["quote"][0]
            adj = j["indicators"].get("adjclose", [{}])[0].get("adjclose", qu["close"])
            off = j["meta"].get("gmtoffset", 0)
            out = []
            for i, t in enumerate(ts):
                c = qu["close"][i]
                if c is None:
                    continue
                d = datetime.fromtimestamp(t + off, tz=timezone.utc).strftime("%Y-%m-%d")
                o, h, l = qu["open"][i] or c, qu["high"][i] or c, qu["low"][i] or c
                out.append((d, o, h, l, c, adj[i] if adj[i] is not None else c))
            # 같은 날짜 중복 제거 (장중 마지막 봉)
            ded = {}
            for r in out:
                ded[r[0]] = r
            rows = [ded[k] for k in sorted(ded)]
            if len(rows) > 300:
                gaps = [(datetime.strptime(rows[i][0], "%Y-%m-%d") - datetime.strptime(rows[i-1][0], "%Y-%m-%d")).days for i in range(len(rows)-250, len(rows))]
                if max(gaps) > 10:
                    raise ValueError(f"{sym}: 일봉이 아님 (간격 {max(gaps)}일)")
            return rows
        except Exception as e:  # noqa
            err = e
    raise err


def naver(code, count=800):
    txt = http_get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0")
    out = []
    for part in txt.split('data="')[1:]:
        f = part.split('"')[0].split("|")
        d = f"{f[0][:4]}-{f[0][4:6]}-{f[0][6:8]}"
        o, h, l, c = (float(x) for x in f[1:5])
        out.append((d, o, h, l, c, c))
    return out


def fred(series, start):
    key = os.environ.get("FRED_API_KEY")
    if key:  # 공식 API (무료 키) — 러너 IP 차단 회피
        j = json.loads(http_get(f"https://api.stlouisfed.org/fred/series/observations?series_id={series}&observation_start={start}&api_key={key}&file_type=json", headers={"User-Agent": "invest-dashboard/1.0"}))
        return [(o["date"], float(o["value"])) for o in j["observations"] if o["value"] not in (".", "")]
    txt = http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}", headers={"User-Agent": "invest-dashboard/1.0 (python-urllib)"})
    rows = []
    for r in csv.reader(io.StringIO(txt)):
        if not r or r[0].lower().startswith(("date", "observation")):
            continue
        try:
            rows.append((r[0], float(r[1])))
        except ValueError:
            pass
    return rows


def cnn_fng():
    try:
        j = json.loads(http_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", tries=2, headers={"Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}))
        fg = j["fear_and_greed"]
        return {"score": round(fg["score"], 1), "rating": fg["rating"], "date": fg["timestamp"][:10],
                "prev_week": round(fg.get("previous_1_week", 0) or 0, 1)}
    except Exception as e:
        print("CNN fail", e, flush=True)
        return None


# ---------- 지표 ----------
def sma(c, n, i=None):
    i = len(c) - 1 if i is None else i
    if i + 1 < n:
        return None
    return sum(c[i - n + 1:i + 1]) / n


def rsi_series(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    out[n] = 100 - 100 / (1 + g / l) if l else 100
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + g / l) if l else 100
    return out


def weekly(rows):
    """일봉 → 주봉 종가 (ISO 주 기준)"""
    wk = {}
    for r in rows:
        y, w, _ = datetime.strptime(r[0], "%Y-%m-%d").isocalendar()
        wk[(y, w)] = r[4]
    return [wk[k] for k in sorted(wk)]


def r2(x, n=2):
    return None if x is None else round(x, n)


def summarize(sym, name, group, cur, rows):
    c = [r[4] for r in rows]
    last, prev = c[-1], c[-2] if len(c) > 1 else c[-1]
    ath = max(c)
    hi52 = max(c[-252:])
    rs = rsi_series(c)
    ma = {n: sma(c, n) for n in (5, 20, 50, 60, 120, 200)}
    w = weekly(rows)
    rw = rsi_series(w)
    ma50w = sma(w, 50)
    # 최근 3거래일 안에 이평선 터치(저가 ≤ 이평선 × 1.005)
    touch = {}
    for n in (20, 60, 120, 200):
        t = False
        for k in range(1, 4):
            if len(c) - k < n:
                break
            m = sma(c, n, len(c) - k)
            if rows[-k][3] <= m * 1.005:
                t = True
        touch[f"ma{n}"] = t
    return {
        "name": name, "group": group, "cur": cur, "date": rows[-1][0],
        "price": r2(last, 4), "prev": r2(prev, 4), "chg": r2((last / prev - 1) * 100),
        "ath": r2(ath, 4), "dd_ath": r2((last / ath - 1) * 100),
        "high52": r2(hi52, 4), "dd52": r2((last / hi52 - 1) * 100),
        "ma": {str(k): r2(v, 4) for k, v in ma.items()},
        "vs200": r2((last / ma[200] - 1) * 100) if ma[200] else None,
        "vs50": r2((last / ma[50] - 1) * 100) if ma[50] else None,
        "rsi": r2(rs[-1], 1), "rsi_w": r2(rw[-1], 1),
        "gap50w": r2(last / ma50w * 100, 1) if ma50w else None,
        "touch": touch,
        "spark": [r2(x, 4) for x in c[-120:]],
        "spark_dates": [rows[-120:][0][0], rows[-1][0]],
    }


def qqq_state_series(rows, vix_by_date):
    """플레이북 5상태 일별 판정. 1 상승 / 2 조정 / 3 추세이탈 / 4 폭락 / 5 회복"""
    c = [r[4] for r in rows]
    states, peak = [], 0
    st = 2
    below = above = 0
    for i in range(len(c)):
        peak = max(peak, c[i])
        m200, m50 = sma(c, 200, i), sma(c, 50, i)
        if m200 is None:
            states.append(None); continue
        dd = c[i] / peak - 1
        below = below + 1 if c[i] < m200 * 0.97 else 0
        above = above + 1 if c[i] > m200 * 1.03 else 0
        vix = vix_by_date.get(rows[i][0])
        crash = dd <= -0.25 and (vix is not None and vix >= 35)
        if below >= 2:
            st = 4 if crash else 3
        elif st in (3, 4):
            if above >= 2:
                st = 5
            elif st == 4 and not crash:
                st = 3 if c[i] < m200 else st
        elif st == 5:
            if c[i] > m50 > m200 and dd > -0.10:
                st = 1
        else:
            st = 1 if (c[i] > m50 > m200 and dd > -0.10) else 2
        states.append(st)
    return states


def macro_block(start):
    m = {}
    fails = 0
    for k, sid in FRED.items():
        if fails >= 3:  # FRED 차단·장애 시 전체 대기 방지
            m[k] = []; continue
        t0 = time.time()
        try:
            m[k] = fred(sid, start)
            print(f"FRED {sid} {len(m[k])} rows {time.time()-t0:.1f}s", flush=True)
        except Exception as e:  # noqa
            fails += 1
            print(f"FRED fail {sid} {e} {time.time()-t0:.1f}s", flush=True)
            m[k] = []
    out = {}

    def last(k):
        return m[k][-1] if m[k] else (None, None)

    for k in ("hy", "t10y2y", "dgs2", "fedu", "sahm", "unrate", "sofr", "iorb", "vix"):
        d, v = last(k)
        out[k] = {"v": v, "date": d, "spark": [x[1] for x in m[k][-260:]]}
    # HY 4주 변화
    if len(m["hy"]) > 21:
        out["hy"]["chg4w"] = round(m["hy"][-1][1] - m["hy"][-21][1], 2)
    # 기준금리 변경 이력 (최근 12개월)
    ch = []
    f = m["fedu"]
    for i in range(1, len(f)):
        if abs(f[i][1] - f[i - 1][1]) > 1e-9:
            ch.append({"date": f[i][0], "delta": round(f[i][1] - f[i - 1][1], 3)})
    out["fedu"]["changes"] = ch[-8:]
    # 실업수당
    ic = m["icsa"]
    if ic:
        out["icsa"] = {"v": ic[-1][1], "date": ic[-1][0], "avg4": round(sum(x[1] for x in ic[-4:]) / min(4, len(ic))),
                       "spark": [x[1] for x in ic[-104:]]}
    # 순유동성 = WALCL - TGA - RRP (단위: 십억 달러). WALCL/TGA 백만, RRP 십억
    try:
        rrp = dict(m["rrp"]); tga = dict(m["tga"])
        rrp_dates = sorted(rrp)
        nl = []
        for d, w in m["walcl"]:
            if d not in tga:
                continue
            rd = [x for x in rrp_dates if x <= d]
            if not rd:
                continue
            nl.append((d, round(w / 1000 - tga[d] / 1000 - rrp[rd[-1]], 1)))
        down = 0
        for i in range(len(nl) - 1, 0, -1):
            if nl[i][1] < nl[i - 1][1]:
                down += 1
            else:
                break
        out["netliq"] = {"v": nl[-1][1], "date": nl[-1][0],
                         "chg4w": round(nl[-1][1] - nl[-5][1], 1) if len(nl) > 5 else None,
                         "chg13w": round(nl[-1][1] - nl[-14][1], 1) if len(nl) > 14 else None,
                         "weeks_down": down, "spark": [x[1] for x in nl[-104:]],
                         "walcl": m["walcl"][-1][1] / 1000, "tga": tga[nl[-1][0]] / 1000, "rrp": rrp[rrp_dates[-1]]}
    except Exception as e:  # noqa
        print("netliq fail", e, file=sys.stderr)
    return out, m


# ---------- 백테스트 ----------
def stats(curve, dates):
    yrs = (datetime.strptime(dates[-1], "%Y-%m-%d") - datetime.strptime(dates[0], "%Y-%m-%d")).days / 365.25
    cagr = (curve[-1] / curve[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    pk, mdd = curve[0], 0
    for v in curve:
        pk = max(pk, v); mdd = min(mdd, v / pk - 1)
    return {"cagr": round(cagr * 100, 2), "mdd": round(mdd * 100, 1), "mult": round(curve[-1] / curve[0], 2)}


def bt_minus3(idx_rows, trade_rows, vix_by_date, label, lev=1.0, cash_rate=0.0):
    """조던 -3% 룰: 신호 지수 일간 -3% 이하 마감 → 종가 전량 매도, 23거래일 후 재매수.
    23거래일 안에 -3%가 4회면 '공황' → 42거래일 대기. 예외: 8거래일 연속 상승 또는 VIX ≤ 15면 조기 재진입.
    trade_rows: 실제 보유 자산 (adjclose 사용). lev>1이면 일간 수익률 × lev (일일 리밸런싱 레버리지 근사, 비용 연 1% 차감)."""
    sig = {r[0]: r[4] for r in idx_rows}
    sig_dates = [r[0] for r in idx_rows]
    sig_prev = {sig_dates[i]: sig[sig_dates[i - 1]] for i in range(1, len(sig_dates))}
    rows = [r for r in trade_rows if r[0] in sig_prev]
    dates = [r[0] for r in rows]
    px = [r[5] for r in rows]
    hold = bh = 1.0
    curve, bh_curve = [1.0], [1.0]
    inmkt, wait, trades, days_in = True, 0, 0, 0
    minus3_hist = []
    up_streak = 0
    daily_cost = 0.01 / 252 if lev > 1 else 0
    for i in range(1, len(rows)):
        r = (px[i] / px[i - 1] - 1) * lev - daily_cost
        bh *= max(1 + r, 0.0001)
        if inmkt:
            hold *= max(1 + r, 0.0001); days_in += 1
        else:
            hold *= 1 + cash_rate / 252
        d = dates[i]
        s_chg = sig[d] / sig_prev[d] - 1
        up_streak = up_streak + 1 if s_chg > 0 else 0
        minus3_hist = [k for k in minus3_hist if i - k < 23]
        if s_chg <= -0.03:
            minus3_hist.append(i)
            if inmkt:
                inmkt = False; trades += 1
            wait = 42 if len(minus3_hist) >= 4 else max(wait, 23)
        elif not inmkt:
            wait -= 1
            v = vix_by_date.get(d)
            if wait <= 0 or up_streak >= 8 or (v is not None and v <= 15):
                inmkt = True; wait = 0
        curve.append(hold); bh_curve.append(bh)
    return {
        "label": label, "start": dates[0], "end": dates[-1],
        "rule": stats(curve, dates), "hold": stats(bh_curve, dates),
        "sells": trades, "time_in_market": round(days_in / (len(rows) - 1) * 100, 1),
        "curve": downsample(dates, curve, bh_curve),
    }


def downsample(dates, a, b, n=160):
    step = max(1, len(dates) // n)
    idx = list(range(0, len(dates), step))
    if idx[-1] != len(dates) - 1:
        idx.append(len(dates) - 1)
    return [[dates[i], round(a[i], 4), round(b[i], 4)] for i in idx]


def bt_dca(qqq_rows, qld_rows, label):
    """월 적립 비교 (QLD 1층 규칙 단순화):
    A 무지성: 매월 첫 거래일 QLD 1단위 매수
    B -2% 규칙: 월초 1단위 적립 → 당월 QLD 전일 대비 -2% 이하 날에 매수(RSI≤50이면 2배 분량), 월말 미집행분 절반 매수·절반 이월(최대 3단위)
    C 1배 QQQ 무지성 (기준선)"""
    q = {r[0]: r[5] for r in qqq_rows}
    rows = [r for r in qld_rows if r[0] in q]
    dates = [r[0] for r in rows]; px = [r[5] for r in rows]; cl = [r[4] for r in rows]
    rs = rsi_series([q[d] for d in dates])
    shA = shB = shC = 0.0
    cashB = 0.0; inv = 0.0
    month = None
    out = []
    for i in range(1, len(rows)):
        mo = dates[i][:7]
        new_month = mo != month
        if new_month:
            if month is not None:  # 전월 마감: 미집행분 절반 매수, 이월은 3단위 한도
                spend = cashB / 2
                if cashB - spend > 3:
                    spend = cashB - 3
                shB += spend / px[i - 1]; cashB -= spend
            month = mo
            inv += 1
            shA += 1 / px[i]; shC += 1 / q[dates[i]]
            cashB += 1
        chg = cl[i] / cl[i - 1] - 1
        if chg <= -0.02 and cashB > 0:
            unit = 2 if (rs[i] is not None and rs[i] <= 50) else 1
            spend = min(cashB, unit * 0.25)
            shB += spend / px[i]; cashB -= spend
        out.append((dates[i], shA * px[i], shB * px[i] + cashB, shC * q[dates[i]], inv))
    last = out[-1]
    def mdd(k):
        pk, m = 0, 0
        for r in out:
            v = r[k] / r[4]
            pk = max(pk, v); m = min(m, v / pk - 1)
        return round(m * 100, 1)
    return {
        "label": label, "start": out[0][0], "end": last[0], "months": int(last[4]),
        "invested": last[4],
        "A_qld_monthly": {"value": round(last[1], 2), "mult": round(last[1] / last[4], 2), "mdd": mdd(1)},
        "B_qld_dip2": {"value": round(last[2], 2), "mult": round(last[2] / last[4], 2), "mdd": mdd(2)},
        "C_qqq_monthly": {"value": round(last[3], 2), "mult": round(last[3] / last[4], 2), "mdd": mdd(3)},
    }


def main():
    os.makedirs(DATA, exist_ok=True)
    now = datetime.now(timezone.utc)
    hist, symbols, errors = {}, {}, []
    for sym, name, group, cur, src in SYMBOLS:
        try:
            rng = "max" if sym in ("QQQ", "^IXIC", "QLD", "^VIX", "TQQQ") else "10y"
            rows = yahoo(sym, rng) if src == "y" else naver(sym)
            hist[sym] = rows
            symbols[sym] = summarize(sym, name, group, cur, rows)
        except Exception as e:  # noqa
            errors.append(f"{sym}: {e}")
            print("price fail", sym, e, flush=True)
        time.sleep(0.4)

    vix_by_date = {r[0]: r[4] for r in hist.get("^VIX", [])}
    if "QQQ" in hist:
        st = qqq_state_series(hist["QQQ"], vix_by_date)
        q = symbols["QQQ"]
        q["state"] = st[-1]
        q["state_hist"] = [[hist["QQQ"][i][0], st[i]] for i in range(len(st) - 60, len(st))]
        c = [r[4] for r in hist["QQQ"]]
        q["below97_streak"] = 0
        for i in range(len(c) - 1, 0, -1):
            m = sma(c, 200, i)
            if m is not None and c[i] < m * 0.97:
                q["below97_streak"] += 1
            else:
                break
        q["above103_streak"] = 0
        for i in range(len(c) - 1, 0, -1):
            m = sma(c, 200, i)
            if m is not None and c[i] > m * 1.03:
                q["above103_streak"] += 1
            else:
                break
        # 사이클 고점일 (실탄 차수 리셋 판단용)
        pk = max(range(len(c)), key=lambda i: c[i])
        q["ath_date"] = hist["QQQ"][pk][0]
    if "^IXIC" in hist:
        c = [r[4] for r in hist["^IXIC"]]
        chg = [(c[i] / c[i - 1] - 1) * 100 for i in range(len(c) - 23, len(c))]
        symbols["^IXIC"]["minus3_23d"] = sum(1 for x in chg if x <= -3)
        symbols["^IXIC"]["minus3_dates"] = [hist["^IXIC"][len(c) - 23 + i][0] for i, x in enumerate(chg) if x <= -3]

    print("prices done", len(symbols), flush=True)
    start = (now - timedelta(days=800)).strftime("%Y-%m-%d")
    macro, raw = macro_block(start)
    print("macro done", flush=True)
    fng = cnn_fng()
    print("fng", fng, flush=True)

    market = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fx": {"usdkrw": symbols.get("KRW=X", {}).get("price")},
        "symbols": symbols, "macro": macro, "fng": fng, "errors": errors,
        "snapshot": False,
    }
    with open(os.path.join(DATA, "market.json"), "w", encoding="utf-8") as f:
        json.dump(market, f, ensure_ascii=False, separators=(",", ":"))

    # 백테스트는 하루 1회면 충분 (미국 장 마감 후 실행분 또는 파일 없을 때)
    bt_path = os.path.join(DATA, "backtest.json")
    need_bt = not os.path.exists(bt_path) or now.hour in (21, 22) or os.environ.get("FORCE_BT")
    if need_bt and all(k in hist for k in ("^IXIC", "QQQ", "QLD")):
        bt = {"generated": market["generated"], "minus3": [], "dca": []}
        ix, qq, ql = hist["^IXIC"], hist["QQQ"], hist["QLD"]
        bt["minus3"].append(bt_minus3(ix, qq, vix_by_date, "QQQ 1배 (1999~)"))
        bt["minus3"].append(bt_minus3(ix, ql, vix_by_date, "QLD 2배 (2006~)"))
        bt["minus3"].append(bt_minus3(ix, qq, vix_by_date, "QQQ×3 합성 (1999~, TQQQ 근사)", lev=3.0))
        recent = [r for r in qq if r[0] >= "2016-01-01"]
        bt["minus3"].append(bt_minus3(ix, recent, vix_by_date, "QQQ 1배 최근 10년 (2016~)"))
        bt["dca"].append(bt_dca(qq, ql, "QLD 월 적립 (2006~)"))
        bt["dca"].append(bt_dca(qq, [r for r in ql if r[0] >= "2016-01-01"], "QLD 월 적립 최근 10년 (2016~)"))
        with open(bt_path, "w", encoding="utf-8") as f:
            json.dump(bt, f, ensure_ascii=False, separators=(",", ":"))
    print("ok", len(symbols), "symbols,", len(errors), "errors")


if __name__ == "__main__":
    main()
