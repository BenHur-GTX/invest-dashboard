#!/usr/bin/env python3
"""시세·거시 데이터 수집 + 지표 계산 + 백테스트 → data/market.json, data/backtest.json

GitHub Actions에서 실행한다 (표준 라이브러리만 사용).
데이터: Yahoo Finance chart API(15분 지연), Naver 차트(국내 ETF), FRED fredgraph.csv(키 불필요),
CNN 공포탐욕(비공식, 실패해도 무시).
"""
import bisect, csv, io, json, math, os, sys, time, urllib.request, urllib.error
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
    ("^KQ11", "코스닥", "지수", "KRW", "y"),   # 11-20 Ben: 고점 대비 하락률 비교
    ("KRW=X", "원/달러", "지수", "KRW", "y"),
    ("JPYKRW=X", "원/엔", "지수", "KRW", "y"),
    ("CL=F", "WTI 유가", "지수", "USD", "y"),   # 11-21 Ben: 유가(배럴). 거시 점검 탭 판정 카드 + 시세 지수 표
    ("QQQM", "QQQM", "1배 지수", "USD", "y"),
    ("SPYM", "SPYM", "1배 지수", "USD", "y"),
    ("MGK", "MGK", "1배 지수", "USD", "y"),
    ("TOPT", "Top20", "1배 지수", "USD", "y"),   # 11-21 Ben: iShares Top 20 U.S. Stocks ETF. 시세 탭 표시용(적립·추천 규칙엔 넣지 않음)
    ("QNDX", "QNDX (나스닥100 1배)", "1배 지수", "USD", "y"),   # 11-25 Ben 장투 보유. 시세·평가용(적립·추천 규칙엔 넣지 않음)
    # 섹터: SPDR 11개 섹터 + 반도체 SOXX (11-08 Ben, 중복 SMH 제외)
    ("XLK", "기술", "섹터", "USD", "y"),
    ("SOXX", "반도체", "섹터", "USD", "y"),
    ("XLC", "커뮤니케이션", "섹터", "USD", "y"),
    ("XLY", "경기소비재", "섹터", "USD", "y"),
    ("XLP", "필수소비재", "섹터", "USD", "y"),
    ("XLV", "헬스케어", "섹터", "USD", "y"),
    ("XLF", "금융", "섹터", "USD", "y"),
    ("XLI", "산업재", "섹터", "USD", "y"),
    ("XLE", "에너지", "섹터", "USD", "y"),
    ("XLB", "소재", "섹터", "USD", "y"),
    ("XLU", "유틸리티", "섹터", "USD", "y"),
    ("XLRE", "부동산", "섹터", "USD", "y"),
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
    # 금·비트코인 (11-13 Ben). IBIT은 국내 증권사 매수 불가, 비트코인 현물 가격 참고용
    ("GLD", "금 (GLD)", "금·비트코인", "USD", "y"),
    ("BITO", "비트코인 선물 1배", "금·비트코인", "USD", "y"),
    ("BITU", "비트코인 2배", "금·비트코인", "USD", "y"),
    ("IBIT", "비트코인 현물 (참고, 국내 매수 불가)", "금·비트코인", "USD", "y"),
    ("BTC-USD", "비트코인 현물 (BITO 상한 낙폭 기준)", "금·비트코인", "USD", "y"),   # 11-14 Ben: 고점 −70% 6%, −80% 9%
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
    ("SPCX", "스페이스X", "빅테크", "USD", "y"),   # 11-14 Ben. 2026-06-12 상장(나스닥), 이력 짧아 200일선 없음
    ("ANT", "앤트로픽", "빅테크", "USD", "y"),   # 11-20 Ben. 2026-11-19 상장(나스닥). 이력 1~2일이라 200일선·40주선·RSI·%B 없음
    # 관심 성장주 (11-14 Ben): 모니터링 위주. 스윙 신호는 1년 고점 −70% + RSI ≤ 30, 1회 12.5% (index.html SWING_TH.g)
    ("IONQ", "아이온큐", "성장주", "USD", "y"),
    ("RKLB", "로켓랩", "성장주", "USD", "y"),
    # 11-18 Ben 추가: 성장주 심리 지표
    ("IREN", "아이렌 (AI 데이터센터)", "성장주", "USD", "y"),
    ("PLTR", "팔란티어", "성장주", "USD", "y"),   # 개인 투자자 성장주 심리 대표
    ("CRSP", "크리스퍼 (바이오)", "성장주", "USD", "y"),   # ARKG 대표 보유, 고변동 바이오
    ("ARKK", "ARK 혁신 ETF", "성장주", "USD", "y"),
    ("ARKG", "ARK 유전체 ETF", "성장주", "USD", "y"),
    # 국내 상장 (연금·IRP)
    ("069500", "KODEX 200", "국내", "KRW", "n"),
    ("360750", "TIGER 미국S&P500", "국내", "KRW", "n"),
    ("426030", "TIME 미국나스닥100액티브", "국내", "KRW", "n"),
    ("133690", "TIGER 미국나스닥100", "국내", "KRW", "n"),
    ("0048J0", "KODEX 미국머니마켓액티브", "국내", "KRW", "n"),
    ("0046A0", "TIGER 미국초단기국채", "국내", "KRW", "n"),
    ("0137W0", "KIWOOM 미국S&P500&GOLD", "국내", "KRW", "n"),
    ("458730", "TIGER 미국배당다우존스", "국내", "KRW", "n"),
    # 11-22 Ben: 국내 상장 ETF 추가(커버드콜·금). 표시용이며 적립·추천 규칙은 그대로
    ("486290", "TIGER 미국나스닥100타겟데일리커버드콜", "국내", "KRW", "n"),
    ("441640", "KODEX 미국배당커버드콜액티브", "국내", "KRW", "n"),
    ("473640", "HANARO 글로벌금채굴기업", "국내", "KRW", "n"),
    ("411060", "ACE KRX금현물", "국내", "KRW", "n"),
    # 11-22 Ben: 국내 상장 미국 빅테크 집중 ETF(Yahoo 465580.KS). 표시용이며 적립·추천 규칙은 그대로
    ("465580", "ACE 미국빅테크TOP7 Plus", "국내", "KRW", "n"),
    # 11-22 Ben: 국내 상장 200 위클리 커버드콜 ETF. 표시용이며 적립·추천 규칙은 그대로
    ("498400", "KODEX 200타겟위클리커버드콜", "국내", "KRW", "n"),
]

FRED = {
    "hy": "BAMLH0A0HYM2", "t10y2y": "T10Y2Y", "dgs2": "DGS2", "dgs10": "DGS10", "fedu": "DFEDTARU",
    "sahm": "SAHMREALTIME", "unrate": "UNRATE", "icsa": "ICSA",
    "walcl": "WALCL", "tga": "WTREGEN", "rrp": "RRPONTSYD", "sofr": "SOFR", "iorb": "IORB",
    "vix": "VIXCLS",
    # 11-18 Ben: 경고용 (판정 미반영). CCC·BB는 FRED가 최근 3년만 제공
    "ccc": "BAMLH0A3HYC", "bb": "BAMLH0A1HYBB", "sloos": "DRTSCILM",
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


# ---------- 유사 폭락장 궤적 (11-23 Ben) ----------
# 거시 점검 탭 '유사 폭락장 · 현재 위치' 카드용. 최근 2년(약 504거래일) 최고 종가를 고점으로 잡고,
# 고점일부터 최신 거래일까지 거래일차(0..N)와 고점 대비 하락률(%)을 담는다. 화면은 dd ≤ -15%일 때만 그린다.
CRASH_LOOK = 504


def crash_track(rows, vix_rows=None, macro=None):
    c = [r[4] for r in rows]
    n = len(c)
    if n < 30:
        raise ValueError("too few bars")
    lo = max(0, n - CRASH_LOOK)
    pk = max(range(lo, n), key=lambda i: c[i])
    peak = c[pk]
    pts = [[i - pk, round((c[i] / peak - 1) * 100, 1)] for i in range(pk, n)]
    if len(pts) > 400:   # 아주 긴 하락이면 하루 걸러 담아 파일 크기를 묶는다 (마지막 날은 유지)
        pts = pts[::2] + ([pts[-1]] if (len(pts) - 1) % 2 else [])
    out = {"peak_date": rows[pk][0], "peak": round(peak, 2), "days": n - 1 - pk,
           "dd": round((c[-1] / peak - 1) * 100, 1), "points": pts, "live": {}}
    live = out["live"]
    mk = macro or {}
    # 10년물·장단기차·연준 기조는 이번 실행에서 이미 받아 둔 macro 값을 그대로 쓴다
    if mk.get("dgs10", {}).get("v") is not None:
        live["us10y"] = mk["dgs10"]["v"]
    if mk.get("t10y2y", {}).get("v") is not None:
        live["curve"] = mk["t10y2y"]["v"]
    f = mk.get("fedu") or {}
    ch = f.get("changes") or []
    if ch:
        try:
            ago = (datetime.strptime(rows[-1][0], "%Y-%m-%d") - datetime.strptime(ch[-1]["date"], "%Y-%m-%d")).days
        except Exception:  # noqa
            ago = 999
        live["fed"] = ("hike" if ch[-1]["delta"] > 0 else "cut") if ago <= 240 else "hold"
        live["fedchg"] = ch[-1]["delta"]
        live["fed_date"] = ch[-1]["date"]
    if vix_rows:   # 고점 이후 최고 VIX — 과거 하락장의 '구간 최고 VIX'와 같은 방식
        vs = [r[4] for r in vix_rows if r[0] >= out["peak_date"]]
        if vs:
            live["vix_max"] = round(max(vs), 1)
    # 신용 스프레드: FRED 무료 하이일드 이력이 2023-11부터라 과거 비교는 Baa−10년(1986~)으로 통일한다
    try:
        baa = [x for x in fred("BAA10Y", out["peak_date"]) if x[0] >= out["peak_date"]]
        if baa:
            live["cred"] = round(baa[-1][1], 2)
            live["cred0"] = round(baa[0][1], 2)
            live["cred_max"] = round(max(x[1] for x in baa), 2)
    except Exception as e:  # noqa
        print("crash cred fail", e, flush=True)
    return out


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
            # 11-20: 장 마감 직후 Yahoo 일봉 목록에서 당일 봉이 잠깐 빠지는 경우가 있음(11-20 02:19Z 실행이 11-18 종가로 되돌아감).
            # meta의 정규장 가격·시각이 마지막 봉보다 새로우면 그 값으로 당일 봉을 채운다.
            m = j["meta"]; mt, mp = m.get("regularMarketTime"), m.get("regularMarketPrice")
            if mt and mp and rows:
                md = datetime.fromtimestamp(mt + off, tz=timezone.utc).strftime("%Y-%m-%d")
                if md > rows[-1][0]:
                    rows.append((md, mp, m.get("regularMarketDayHigh") or mp, m.get("regularMarketDayLow") or mp, mp, mp))
            if len(rows) > 300:
                gaps = [(datetime.strptime(rows[i][0], "%Y-%m-%d") - datetime.strptime(rows[i-1][0], "%Y-%m-%d")).days for i in range(len(rows)-250, len(rows))]
                if max(gaps) > 10:
                    raise ValueError(f"{sym}: 일봉이 아님 (간격 {max(gaps)}일)")
            return rows
        except Exception as e:  # noqa
            err = e
    raise err


def yahoo_meta(sym):
    """11-21 Ben: chart API meta (최신 호가 regularMarketPrice·직전 종가 chartPreviousClose)"""
    q = urllib.request.quote(sym)
    for host in ("query1", "query2"):
        try:
            j = json.loads(http_get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range=1d&interval=15m"))["chart"]["result"][0]
            return j.get("meta") or {}
        except Exception as e:  # noqa
            err = e
    raise err


# ---------- 시가총액 1~12위 (11-21 Ben) ----------
# 시세 탭 '빅테크': MAGS(대표 바스켓) 아래에 실제 미국·글로벌 시가총액 1~12위를 시총 순으로 세운다.
# Yahoo quote API(getcrumb + v7/finance/quote)로 실시간 marketCap을 받고, 실패하면 지난 저장값 순서로 폴백.
BT_N = 12
BT_UNIVERSE = [   # 시총 상위 후보군 (2026-11-21 확인: 12위 LLY 1.20T, 13위 ANT 1.19T, 14위 WMT 1.02T)
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK-B", "TSM", "SPCX", "ANT",
    "LLY", "WMT", "JPM", "V", "ORCL", "XOM", "MA", "UNH", "COST", "NFLX",
    "AMD", "JNJ", "ABBV", "ASML", "KO", "PG",   # 12위 근처까지 확인용 (0.4T 이상)
]
BT_NAMES = {"LLY": "일라이릴리", "WMT": "월마트", "JPM": "JP모건", "V": "비자", "ORCL": "오라클",
            "XOM": "엑슨모빌", "MA": "마스터카드", "UNH": "유나이티드헬스", "COST": "코스트코",
            "NFLX": "넷플릭스", "AMD": "AMD", "JNJ": "존슨앤존슨", "ABBV": "애브비", "ASML": "ASML",
            "KO": "코카콜라", "PG": "P&G"}
BT_BARS = {}   # 연초 종가만 필요한 종목의 1년 일봉 캐시


def yahoo_quotes(syms, chunk=12):
    """v7/finance/quote → {sym: {mcap, price, chg}}. crumb은 쿠키(A3)를 심은 뒤 받아야 한다."""
    import http.cookiejar
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def g(u, tries=3):
        last = None
        for i in range(tries):   # crumb은 이 세션(A3 쿠키)에 묶인다 → 같은 opener로 받아야 함
            try:
                req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
                with op.open(req, timeout=20) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:  # noqa
                last = e
                time.sleep(1.5 * (i + 1))
        raise last
    crumb = ""
    try:
        try:
            g("https://fc.yahoo.com")   # 404지만 쿠키가 심긴다 (없으면 crumb 401)
        except Exception:  # noqa
            pass
        crumb = g("https://query2.finance.yahoo.com/v1/test/getcrumb").strip()
    except Exception as e:  # noqa
        print("crumb fail", e, flush=True)
    out = {}
    for i in range(0, len(syms), chunk):
        u = "https://query2.finance.yahoo.com/v7/finance/quote?symbols=" + urllib.request.quote(",".join(syms[i:i + chunk]))
        if crumb:
            u += "&crumb=" + urllib.request.quote(crumb)
        j = json.loads(g(u))
        for q in j.get("quoteResponse", {}).get("result", []):
            mc, p = q.get("marketCap"), q.get("regularMarketPrice")
            if not mc or not p:
                continue
            out[q["symbol"]] = {"mcap": float(mc), "price": float(p), "chg": q.get("regularMarketChangePercent")}
        time.sleep(0.3)
    return out


def bt_bars(sym, hist):
    if sym in hist:
        return hist[sym]
    if sym not in BT_BARS:
        try:
            BT_BARS[sym] = yahoo(sym, "1y")
        except Exception as e:  # noqa
            print("bt bars fail", sym, e, flush=True)
            BT_BARS[sym] = []
    return BT_BARS[sym]


def jan_adj(sym, hist, ref):
    """올해 첫 거래일 수정주가와 최신 수정주가. 연초 상장 전이면 (None, None)."""
    rows = bt_bars(sym, hist)
    if not rows or not ref:
        return None, None
    hit = next((r for r in rows if r[0] >= ref), None)
    if not hit:
        return None, None
    if abs((datetime.strptime(hit[0], "%Y-%m-%d") - datetime.strptime(ref, "%Y-%m-%d")).days) > 4:
        return None, None   # SPCX(2026-06-12)·ANT(2026-11-19)처럼 연초에 없던 종목
    return hit[5], rows[-1][5]


def bigtech_rank(quotes, hist, symbols, prev_block, now):
    """시총 1~12위 + 직전 대비·연초 대비 순위 변동 + 연초 Top12 진입·이탈."""
    year = now.year
    names = {s: v.get("name") for s, v in symbols.items()}

    def nm(s):
        n = names.get(s)
        return n if n and n != s else BT_NAMES.get(s, s)
    ref = None   # 올해 첫 거래일 (QQQ 등 확실한 종목의 일봉에서)
    for s in ("QQQ", "AAPL", "^GSPC", "MSFT"):
        ref = next((r[0] for r in hist.get(s, []) if r[0] >= f"{year}-01-01"), None)
        if ref:
            break
    cur = sorted(((s, q["mcap"]) for s, q in quotes.items()), key=lambda x: -x[1])
    cm = dict(cur)
    top = cur[:BT_N]
    idx = {s: i + 1 for i, (s, _) in enumerate(cur)}
    # 연초 스냅샷: 파일에 있으면 그대로, 없으면 현재 시총 × (연초 종가 / 현재가)로 역산해 저장
    path = os.path.join(DATA, "bigtech_baseline.json")
    try:
        allb = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa
        allb = {}
    snap = allb.get(str(year))
    # 파일이 없거나 지워지면 지난 market.json에 같이 저장한 스냅샷을 이어쓴다
    # (update-data가 market.json만 커밋해도 기준 스냅샷이 해를 넘겨 유지되게)
    if not (snap and snap.get("rows")):
        pb = (prev_block or {}).get("baseline")
        if pb and pb.get("rows") and str(pb.get("date", ""))[:4] == str(year):
            snap = pb
            allb[str(year)] = snap
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(allb, f, ensure_ascii=False, separators=(",", ":"))
            except Exception:  # noqa
                pass
    derived = False
    if not (snap and snap.get("rows")) and ref:
        rows_b = []
        for s, m in cur:
            a0, a1 = jan_adj(s, hist, ref)
            if not a0 or not a1:
                continue
            rows_b.append((m * a0 / a1, s))
        rows_b.sort(key=lambda x: -x[0])
        snap = {"date": ref, "src": "derived", "rows": [{"sym": s, "rank": i + 1, "mcap_t": round(m / 1e12, 2)}
                                                           for i, (m, s) in enumerate(rows_b)]}
        allb[str(year)] = snap
        derived = True
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(allb, f, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:  # noqa
            print("baseline save fail", e, flush=True)
    base = (snap or {}).get("rows") or []
    base_idx = {r["sym"]: r["rank"] for r in base}
    prev_idx = {r["sym"]: r["rank"] for r in (prev_block or {}).get("rows", [])}
    rows = []
    for i, (s, m) in enumerate(top):
        rank, pr, yr = i + 1, prev_idx.get(s), base_idx.get(s)
        rows.append({"rank": rank, "sym": s, "name": nm(s), "mcap_t": round(m / 1e12, 2),
                     "prev_rank": pr, "rank_diff": (pr - rank) if pr else None,
                     "ytd_rank": yr, "ytd_diff": (yr - rank) if yr else None,
                     "is_new": pr is None, "is_ytd_new": (yr is None or yr > BT_N)})
    below = [{"rank": i + 1, "sym": s, "name": nm(s), "mcap_t": round(m / 1e12, 2)}
             for i, (s, m) in enumerate(cur[BT_N:BT_N + 3], start=BT_N)]
    in_top = {s for s, _ in top}
    exited_ytd = [{"sym": r["sym"], "name": nm(r["sym"]), "ytd_rank": r["rank"], "now_rank": idx.get(r["sym"]),
                   "mcap_t": round(cm.get(r["sym"], 0) / 1e12, 2)} for r in base
                  if r["rank"] <= BT_N and r["sym"] not in in_top]
    exited_prev = [{"sym": r["sym"], "name": nm(r["sym"]), "prev_rank": r["rank"], "now_rank": idx.get(r["sym"]),
                    "mcap_t": round(cm.get(r["sym"], 0) / 1e12, 2)} for r in (prev_block or {}).get("rows", [])
                   if r["sym"] not in in_top]
    return {"asof": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "n": BT_N,
            "ytd_date": (snap or {}).get("date"), "ytd_src": "derived" if derived else ((snap or {}).get("src") or "snapshot"),
            "rows": rows, "below": below, "exited_ytd": exited_ytd, "exited_prev": exited_prev,
            "baseline": snap}   # 올해 스냅샷을 market.json에 같이 남겨 해가 바뀜도 유지


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


def week40(rows):
    """주봉 종가 vs 40주 이동평균 (11-14 Ben: 경보 표시용, 매매 규칙 아님). 마감한 주 기준 + 이번 주 진행 중 값"""
    wk = {}
    for r in rows:
        k = datetime.strptime(r[0], "%Y-%m-%d").isocalendar()[:2]
        wk[k] = (r[0], r[4])
    items = [wk[k] for k in sorted(wk)]
    done = items if datetime.strptime(rows[-1][0], "%Y-%m-%d").weekday() == 4 else items[:-1]
    if len(done) < 41:
        return None
    c = [x[1] for x in done]
    up = [None] * len(c)
    for k in range(39, len(c)):
        up[k] = c[k] > sum(c[k - 39:k + 1]) / 40
    ma = sum(c[-40:]) / 40
    kx = next((k for k in range(len(c) - 1, 39, -1) if up[k] != up[k - 1]), None)
    live = items[-1][1]; lma = sum([x[1] for x in (done[-40:-1] if items[-1] is done[-1] else done[-39:])] + [live]) / 40
    return {"week_end": done[-1][0], "close": r2(c[-1], 2), "ma": r2(ma, 2), "up": up[-1], "gap": r2((c[-1] / ma - 1) * 100),
            "cross": None if kx is None else ("golden" if up[kx] else "dead"), "cross_date": None if kx is None else done[kx][0],
            "weeks": None if kx is None else len(c) - 1 - kx, "live_up": live > lma, "live_gap": r2((live / lma - 1) * 100)}


def r2(x, n=2):
    return None if x is None else round(x, n)


def summarize(sym, name, group, cur, rows):
    c = [r[4] for r in rows]
    last, prev = c[-1], c[-2] if len(c) > 1 else c[-1]
    ath = max(c)
    hi52 = max(c[-252:])
    k5 = len(c) - min(1260, len(c)); seg = c[k5:]; pk_i = k5 + seg.index(max(seg))
    cyc_min = (min(c[pk_i:]) / c[pk_i] - 1) * 100   # 5년 고점 이후 최저 낙폭 (반등 가속 판정용)
    hi5y = max(c[-1260:])  # 낙폭 기준: 최근 5년 고점 (초대형 폭락 뒤 수년간 '폭락' 고정 방지)
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
    # 볼린저 밴드(20, 2σ): 하단 이탈 = 분할매수 날짜 보조 신호 (data/indicator_study.json 검증)
    bb_lo = pctb = None
    if len(c) >= 20:
        wv = c[-20:]; mu = sum(wv) / 20; sd = (sum((x - mu) ** 2 for x in wv) / 20) ** 0.5
        bb_lo = mu - 2 * sd; pctb = (last - bb_lo) / (4 * sd) * 100 if sd else 50
    # 11-16 Ben: 일봉 50/200일선 골든·데드 크로스 (최근 400거래일 안 마지막 교차) — 바닥 골든크로스 2차 가속용
    x50 = None
    for k in range(len(c) - 1, max(200, len(c) - 400), -1):
        a, b = sma(c, 50, k), sma(c, 200, k); a0, b0 = sma(c, 50, k - 1), sma(c, 200, k - 1)
        if None in (a, b, a0, b0):
            break
        if (a > b) != (a0 > b0):
            x50 = {"cross": "golden" if a > b else "dead", "date": rows[k][0], "days": len(c) - 1 - k}
            break
    w40 = week40(rows)   # 11-14 Ben: 시세 목록에 종목별 40주선 골든/데드 표시
    # 11-18 Ben: 도망 경보용 월말 종가 10개월선 (마지막 달은 진행 중으로 보고 확정은 직전 월말)
    mc = {}
    for r in rows:
        mc[r[0][:7]] = r[4]
    mk = sorted(mc)
    m10 = None
    if len(mk) >= 11:
        done = mk[:-1]
        sma10 = sum(mc[k] for k in done[-10:]) / 10
        live10 = (sum(mc[k] for k in done[-9:]) + last) / 10
        m10 = {"month": done[-1], "close": r2(mc[done[-1]], 4), "sma10": r2(sma10, 4),
               "gap": r2((mc[done[-1]] / sma10 - 1) * 100), "below": mc[done[-1]] < sma10,
               "live_sma10": r2(live10, 4), "live_gap": r2((last / live10 - 1) * 100), "live_below": last < live10,
               # 최근 6개 마감 월의 10개월선 아래 여부 (도망 경보 몇 개월째인지 계산용, 오래된 것 → 최근)
               "hist": [{"month": done[j], "below": mc[done[j]] < sum(mc[k] for k in done[j - 9:j + 1]) / 10}
                        for j in range(max(9, len(done) - 6), len(done))]}
    return {
        "name": name, "group": group, "cur": cur, "date": rows[-1][0], "w40": w40, "x50": x50, "m10": m10,
        "bb_lo": r2(bb_lo, 4), "bb_pctb": r2(pctb, 0), "bb_break": bool(bb_lo is not None and last < bb_lo),
        "price": r2(last, 4), "prev": r2(prev, 4), "chg": r2((last / prev - 1) * 100),
        "ath": r2(ath, 4), "dd_ath": r2((last / ath - 1) * 100),
        "high52": r2(hi52, 4), "dd52": r2((last / hi52 - 1) * 100),
        "high5y": r2(hi5y, 4), "dd5y": r2((last / hi5y - 1) * 100), "cyc_min": r2(cyc_min),
        "ma": {str(k): r2(v, 4) for k, v in ma.items()},
        "vs200": r2((last / ma[200] - 1) * 100) if ma[200] else None,
        "vs50": r2((last / ma[50] - 1) * 100) if ma[50] else None,
        "rsi": r2(rs[-1], 1), "rsi_w": r2(rw[-1], 1),
        "gap50w": r2(last / ma50w * 100, 1) if ma50w else None,
        "touch": touch,
        "spark": [r2(x, 4) for x in c[-120:]],
        "spark_dates": [rows[-120:][0][0], rows[-1][0]],
        "avg3y": r2(sum(c[-756:]) / len(c[-756:]), 4), "min3y": r2(min(c[-756:]), 4), "max3y": r2(max(c[-756:]), 4),
        "pct3y": r2(sum(1 for x in c[-756:] if x <= last) / len(c[-756:]) * 100, 0),
    }


def qqq_state_series(rows, vix_by_date):
    """플레이북 5상태 일별 판정. 1 상승 / 2 조정 / 3 추세이탈 / 4 폭락 / 5 회복"""
    c = [r[4] for r in rows]
    states, peak = [], 0
    st = 2
    below = above = 0
    for i in range(len(c)):
        peak = max(c[max(0, i - 1259):i + 1])  # 최근 5년 고점
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

    for k in ("hy", "t10y2y", "dgs2", "dgs10", "fedu", "sahm", "unrate", "sofr", "iorb", "vix"):
        d, v = last(k)
        # 11-20 Ben: '추이 (2년)' 그래프 — 일간 지표는 2년(약 520영업일)으로. 월간(사암·실업률)은 데이터가 2년치만 있어 그대로
        out[k] = {"v": v, "date": d, "spark": [x[1] for x in m[k][-520:]]}
    # HY 4주 변화
    if len(m["hy"]) > 21:
        out["hy"]["chg4w"] = round(m["hy"][-1][1] - m["hy"][-21][1], 2)
    # CCC 3개월(63영업일) 변화, BB 대비 차이 · 은행 C&I 대출 기준 강화 비율(분기)
    if m.get("ccc"):
        c = m["ccc"]
        out["ccc"] = {"v": c[-1][1], "date": c[-1][0], "chg3m": round(c[-1][1] - c[-64][1], 2) if len(c) > 64 else None,
                      "bb": m["bb"][-1][1] if m.get("bb") else None, "spark": [x[1] for x in c[-260:]]}
    if m.get("sloos"):
        out["sloos"] = {"v": m["sloos"][-1][1], "date": m["sloos"][-1][0], "hist": [x[1] for x in m["sloos"][-8:]]}
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
    try:
        out["sofr_iorb"] = sofr_iorb(m["sofr"], m["iorb"])
    except Exception as e:  # noqa
        print("sofr_iorb fail", e, file=sys.stderr)
    return out, m


def sofr_iorb(sofr, iorb):
    """11-20 Ben: SOFR−IORB 스프레드(bp). SOFR은 영업일, IORB는 달력일이라 SOFR 날짜마다 그날(없으면 직전) IORB를 맞춤.
    판정(index.html): 5영업일 평균 +5bp 이상이면 노랑 '단기 압력'. 빨강에는 쓰지 않음(2018~ 백테스트상 하락 예고력 없음)."""
    if not sofr or not iorb:
        return None
    io = sorted(iorb)
    io_d = [d for d, _ in io]
    rows = []
    for d, v in sofr:
        i = bisect.bisect_right(io_d, d) - 1
        if i >= 0:
            rows.append((d, round((v - io[i][1]) * 100)))
    if not rows:
        return None
    bp = [x[1] for x in rows]

    def run(th):
        n = 0
        for x in reversed(bp):
            if x < th:
                break
            n += 1
        return n
    return {"spread_bp": bp[-1], "date": rows[-1][0], "avg5": round(sum(bp[-5:]) / min(5, len(bp)), 1),
            "days_over": run(1), "days_over5": run(5), "max20": max(bp[-20:]),
            "hist": [[d, x] for d, x in rows[-260:]]}


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


# ---------- 과매도 분할매수 수익 확률 (11-21 Ben) ----------
# "VIX ≥ 30 + RSI ≤ 30이면 분할매수" 했을 때 N거래일 뒤 플러스 확률·평균 수익률.
# CNN 공포탐욕은 최근 1년만 제공돼 백테스트 조건에 넣지 않고, 현재 3중 조건 표시에만 쓴다.
OVER_H = (("1주", 5), ("2주", 10), ("4주", 20), ("8주", 40), ("12주", 60))
OVER_SYMS = ("SOXL", "TQQQ", "QQQ", "QLD")
# 11-21 Ben: 공포가 깊어질수록 한 단계씩 더 사는 추매 사다리. weight = 그 단계에 넣는 분할 비중(%)
OVER_LADDER = (
    {"key": "s1", "label": "진입", "vix_min": 30.0, "rsi_max": 30.0, "weight": 20},
    {"key": "s2", "label": "심화", "vix_min": 35.0, "rsi_max": 28.0, "weight": 30},
    {"key": "s3", "label": "1차 추매", "vix_min": 40.0, "rsi_max": 25.0, "weight": 30},
    # 4단계는 RSI를 30으로 열어 둔다: 2008·2020처럼 VIX만 45를 넘고 RSI가 25 밑으로 안 내려간 바닥을 잡기 위해
    {"key": "s4", "label": "극단 패닉", "vix_min": 45.0, "rsi_max": 30.0, "weight": 20},
)


def over_tier(rows, vix_by_date, vix_min, rsi_max):
    """조건 충족일(VIX ≥ vix_min & RSI(14) ≤ rsi_max)마다 종가 매수 → h거래일 뒤 종가 수익률."""
    c = [r[4] for r in rows]
    dates = [r[0] for r in rows]
    rs = rsi_series(c)
    idx = [i for i in range(14, len(rows))
           if dates[i] in vix_by_date and vix_by_date[dates[i]] >= vix_min and rs[i] is not None and rs[i] <= rsi_max]
    win, avg, n = {}, {}, {}
    for lab, h in OVER_H:
        rets = [c[i + h] / c[i] - 1 for i in idx if i + h < len(c)]
        n[str(h)] = len(rets)
        win[str(h)] = round(sum(1 for x in rets if x > 0) / len(rets) * 100) if rets else None
        avg[str(h)] = round(sum(rets) / len(rets) * 100, 1) if rets else None
    sig, last = 0, -999   # 5거래일 쿨다운: 연속된 같은 사건을 한 번으로 센다
    for i in idx:
        if i - last >= 5:
            sig += 1
            last = i
    return {"vix_min": vix_min, "rsi_max": rsi_max, "days": len(idx), "signals": sig,
            "last": dates[idx[-1]] if idx else None, "win": win, "avg": avg, "n": n,
            "hist_years": round((len(rows) - 1) / 252)}


def over_ok(t, cur_vix, cur_rsi):
    """지금 이 단계 조건을 실제로 충족하는가."""
    return (cur_vix is not None and cur_rsi is not None
            and cur_vix >= t["vix_min"] and cur_rsi <= t["rsi_max"])


def over_thin(t):
    """표본이 얇은가 — 신호 3회 미만이거나 4주 표본 3일 미만."""
    return t["signals"] < 3 or (t["n"].get("20") or 0) < 3


def over_current_criteria(cur_vix, cur_rsi):
    """① 현 상황 맞춤 기준 — 지금 과매도 국면이면 지금 강도에 맞춘 컷, 평시면 30/30 대기 컷."""
    q = cur_rsi.get("QQQ")
    if cur_vix is not None and cur_vix >= 30 and q is not None and q <= 30:
        mx = max([v for v in cur_rsi.values() if v is not None] or [30.0])
        return {"mode": "now", "vix_min": max(30.0, float(math.floor(cur_vix))),
                "rsi_max": min(30.0, float(math.ceil(mx)))}
    return {"mode": "wait", "vix_min": 30.0, "rsi_max": 30.0}


def over_cands(vix_min, rsi_max):
    """현재 기준에서 표본이 모자랄 때 차례로 넓혀 가는 후보 (마지막은 기본 30/30)."""
    cands = []
    for v, r in ((vix_min, rsi_max), (vix_min, min(30.0, rsi_max + 2)), (vix_min, 30.0),
                 (max(30.0, vix_min - 5), 30.0), (30.0, 30.0)):
        if (v, r) not in cands:
            cands.append((v, r))
    return cands


def oversold_odds(hist, fng):
    """현 상황 맞춤 수익 확률(current) + 상황 악화별 추매 사다리(ladder)."""
    vix = hist.get("^VIX") or []
    vix_by_date = {r[0]: r[4] for r in vix}
    cur_vix = vix[-1][4] if vix else None
    rows_by, cur_rsi = {}, {}
    for sym in OVER_SYMS:
        rows = hist.get(sym)
        if not rows or len(rows) < 40:
            continue
        rows_by[sym] = rows
        cur_rsi[sym] = rsi_series([r[4] for r in rows])[-1]
    crit = over_current_criteria(cur_vix, cur_rsi)
    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cur": {"vix": r2(cur_vix, 1), "vix_date": vix[-1][0] if vix else None,
                "fng": (fng or {}).get("score"), "fng_rating": (fng or {}).get("rating"), "fng_date": (fng or {}).get("date"),
                "symbols": {}},
        "horizons": [[lab, h] for lab, h in OVER_H],
        "current": {**crit, "symbols": []},
        "ladder": {"steps": []},
    }
    rows_out = []
    for sym, rows in rows_by.items():
        c = [r[4] for r in rows]
        out["cur"]["symbols"][sym] = {"rsi": r2(cur_rsi[sym], 1), "price": r2(c[-1], 4), "date": rows[-1][0]}
        # 종목별로 표본 3회 이상이 되는 가장 엄격한 컷을 쓴다(모자라면 30/30까지 넓힘)
        t = None
        for v, r in over_cands(crit["vix_min"], crit["rsi_max"]):
            t = over_tier(rows, vix_by_date, v, r)
            t["loosened"] = (v, r) != (crit["vix_min"], crit["rsi_max"])
            if not over_thin(t):
                break
        t.update({"sym": sym, "rsi": r2(cur_rsi[sym], 1), "price": r2(c[-1], 4), "since": rows[0][0],
                  "fills": bool(over_ok(t, cur_vix, cur_rsi[sym]))})
        rows_out.append(t)
    # 4주(20거래일) 승률 높은 순, 같으면 12주 승률 순
    rows_out.sort(key=lambda x: (-(x["win"].get("20") if x["win"].get("20") is not None else -1),
                                 -(x["win"].get("60") if x["win"].get("60") is not None else -1)))
    out["current"]["symbols"] = rows_out
    cum = 0
    for st in OVER_LADDER:
        cum += st["weight"]
        syms = {}
        for sym, rows in rows_by.items():
            t = over_tier(rows, vix_by_date, st["vix_min"], st["rsi_max"])
            t["active"] = bool(over_ok(st, cur_vix, cur_rsi.get(sym)))
            syms[sym] = t
        out["ladder"]["steps"].append({**st, "cum": cum,
                                        "vix_on": cur_vix is not None and cur_vix >= st["vix_min"],
                                        "symbols": syms})
    return out


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


# ---------- 중앙은행 금 매입 (11-22 Ben) ----------
# thegoldbarometer 공시 집계(주요 27개국 월별 금 보유량, IMF·각국 공시 기반, 1~2개월 시차, 한국 미포함).
# 월별 순증감은 국가별 교집합(pairwise)으로 낸다. 단순 월 합계의 차이는 최신월 보고 국가가 줄어드는 구간에서
# 수천 톤 마이너스로 왜곡된다(예: 2026-09 24개국 → 2026-10 8개국).
CB_GOLD_URL = "https://thegoldbarometer.com/data/gold-reserves-by-country.csv"
CB_GOLD_MIN_PAIRS = 15   # 두 달 연속 보고한 국가가 이만큼은 되는 달만 '확정 월'로 쓴다
CB_GOLD_MONTHS = 36      # 월별 시계열 길이(3년)
CB_GOLD_YEARS = 6        # 연도별 증감 표시 연수(최신 연도 포함)
CB_GOLD_KO = {
    "USA": "미국", "DEU": "독일", "ITA": "이탈리아", "FRA": "프랑스", "RUS": "러시아", "CHN": "중국",
    "CHE": "스위스", "JPN": "일본", "NLD": "네덜란드", "IND": "인도", "TUR": "튀르키예", "SAU": "사우디",
    "GBR": "영국", "PRT": "포르투갈", "KAZ": "카자흐스탄", "ESP": "스페인", "AUT": "오스트리아",
    "BEL": "벨기에", "POL": "폴란드", "THA": "태국", "SGP": "싱가포르", "SWE": "스웨덴",
    "ZAF": "남아프리카공화국", "MEX": "멕시코", "PHL": "필리핀", "AUS": "호주", "IDN": "인도네시아",
}


def _prev_month(m):
    y, mm = int(m[:4]), int(m[5:7])
    mm -= 1
    if mm == 0:
        y, mm = y - 1, 12
    return "%04d-%02d" % (y, mm)


def cb_gold():
    """macro.cb_gold — 월별 순증감·누적·연도별 증감. 실패하면 예외를 올리고 호출부가 지난 값을 유지한다."""
    txt = http_get(CB_GOLD_URL, timeout=30, headers={"Accept": "text/csv,*/*"})
    by = {}
    for r in csv.DictReader(io.StringIO(txt)):
        iso = (r.get("iso3") or "").strip()
        m = (r.get("month") or "").strip()
        if not iso or len(m) != 7:
            continue
        try:
            by.setdefault(iso, {})[m] = float(r.get("tonnes"))
        except (TypeError, ValueError):
            continue
    if not by:
        raise ValueError("no rows")
    months = sorted({m for d in by.values() for m in d})
    net, npairs = {}, {}
    for m in months:
        p = _prev_month(m)
        common = [c for c in by if m in by[c] and p in by[c]]
        if not common:
            continue
        net[m] = sum(by[c][m] - by[c][p] for c in common)
        npairs[m] = len(common)
    conf = [m for m in sorted(net) if npairs[m] >= CB_GOLD_MIN_PAIRS]
    if not conf:
        raise ValueError("no confirmed month")
    latest = conf[-1]
    window = conf[-CB_GOLD_MONTHS:]
    cum, series = 0.0, []
    for m in window:
        cum += net[m]
        series.append({"m": m, "net": round(net[m], 1), "cum": round(cum, 1)})

    # 최신 확정월 기준 국가별 변동폭(순매입 상위 / 순매도 상위)
    p = _prev_month(latest)
    deltas = [(c, by[c][latest] - by[c][p]) for c in by if latest in by[c] and p in by[c]]
    buyers = [{"iso": c, "name": CB_GOLD_KO.get(c, c), "t": round(d, 1)}
              for c, d in sorted([x for x in deltas if x[1] >= 0.05], key=lambda x: -x[1])[:3]]
    sellers = [{"iso": c, "name": CB_GOLD_KO.get(c, c), "t": round(d, 1)}
               for c, d in sorted([x for x in deltas if x[1] <= -0.05], key=lambda x: x[1])[:2]]

    # 연도별 순증감(확정 월의 pairwise 순증감 합). 최신 연도는 확정 월까지만 = YTD
    annual = []
    for y in range(int(latest[:4]) - (CB_GOLD_YEARS - 1), int(latest[:4]) + 1):
        ms = [m for m in conf if m.startswith("%04d-" % y)]
        if not ms:
            continue
        item = {"y": str(y), "net": round(sum(net[m] for m in ms), 1), "n": len(ms)}
        if y == int(latest[:4]) and latest[5:7] != "12":
            item["ytd"] = True
        annual.append(item)

    # 최신월 다음의 선보고(확정 기준 미달) 월 — 메인 시계열에 섞지 않는다
    pre = None
    tail = [m for m in sorted(net) if m > latest]
    if tail:
        pre = {"m": tail[-1], "n": npairs[tail[-1]], "net": round(net[tail[-1]], 1)}

    return {
        "latest_month": latest,
        "latest_net_t": round(net[latest], 1),
        "latest_n": npairs[latest],
        "prev_net_t": round(net[conf[-2]], 1) if len(conf) > 1 else None,
        "total_tonnes": round(sum(by[c][latest] for c in by if latest in by[c]), 1),
        "total_n": sum(1 for c in by if latest in by[c]),
        "cum_3y_t": round(series[-1]["cum"], 1),
        "ytd_t": round(sum(net[m] for m in conf if m.startswith(latest[:4])), 1),
        "top_buyers_latest": buyers,
        "top_sellers_latest": sellers,
        "series": series,
        "annual": annual,
        "preliminary": pre,
        "countries": len(by),
        "source": CB_GOLD_URL,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------- 밸류에이션 (11-23 Ben) ----------
# 거시 점검 탭 '바닥 밸류에이션 (참고)' — S&P 500 12개월 선행 PER.
# historyofmarket.com 공개 JSON(데이터 CC BY 4.0). 주간 'forward'(벤더 컨센서스)는 2026-08-05(20.12배) 이후 갱신이
# 멈춰 있어서, 매일 갱신되는 'forwardOwn'(FY1/FY2 컨센서스·ETF 보유내역 가중, 2026-07-28~)을 현재값으로 쓴다.
# 둘은 2026-08-05 기준 20.12 vs 19.99로 3% 이내다. 값이 없으면 주간 시리즈로 폴백한다.
VALUATION_URL = "https://historyofmarket.com/api/sp500/forward-pe.json"
SP500_FWD_TH = 15.0   # 참고 기준: 15배 이하 (index.html valuationHTML과 같은 값)


def sp500_forward_pe():
    """S&P 500 12개월 선행 PER. 실패하면 예외를 올리고 호출부가 지난 값을 유지한다."""
    j = json.loads(http_get(VALUATION_URL, timeout=30, headers={"Accept": "application/json"}))
    daily = [x for x in (j.get("forwardOwn") or []) if x.get("value") is not None]
    weekly = [x for x in (j.get("forward") or []) if x.get("value") is not None]
    series, basis = (daily, "daily") if daily else (weekly, "weekly")
    if not series:
        raise ValueError("no forward PE series")
    cur = series[-1]
    tr = (j.get("current") or {}).get("trailing")
    return {"v": round(float(cur["value"]), 2), "date": cur.get("date"), "basis": basis,
            "trailing": round(float(tr), 2) if tr is not None else None,
            "th": SP500_FWD_TH, "pts": len(series),
            "source": "historyofmarket.com (CC BY 4.0)", "url": VALUATION_URL,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def main():
    os.makedirs(DATA, exist_ok=True)
    now = datetime.now(timezone.utc)
    # 11-21 Ben: 지난 저장값(market.json)을 덮어쓰기 전에 읽어 두고 직전 순위로 쓴다
    prev_market = {}
    try:
        with open(os.path.join(DATA, "market.json"), encoding="utf-8") as f:
            prev_market = json.load(f)
    except Exception:  # noqa
        prev_market = {}
    # 11-21 Ben: 시총 1~12위를 먼저 받아 두고, 시세 수집 목록에 없는 종목은 빅테크로 추가한다
    bt_quotes, bt_err = {}, None
    try:
        bt_quotes = yahoo_quotes(BT_UNIVERSE)
        print("quote", len(bt_quotes), "market caps", flush=True)
    except Exception as e:  # noqa
        bt_err = repr(e)[:200]
        print("quote fail", e, flush=True)
    roster = list(SYMBOLS)
    known = {s[0] for s in roster}
    for sym, _q in sorted(bt_quotes.items(), key=lambda kv: -kv[1]["mcap"])[:BT_N]:
        if sym not in known:
            roster.append((sym, BT_NAMES.get(sym, sym), "빅테크", "USD", "y"))
    hist, symbols, errors = {}, {}, []
    crash_cur = None
    for sym, name, group, cur, src in roster:
        try:
            rng = "max" if sym in ("QQQ", "^IXIC", "QLD", "^VIX", "TQQQ", "SOXL") else "10y"
            rows = yahoo(sym, rng) if src == "y" else naver(sym)
            hist[sym] = rows
            symbols[sym] = summarize(sym, name, group, cur, rows)
        except Exception as e:  # noqa
            errors.append(f"{sym}: {e}")
            print("price fail", sym, e, flush=True)
        time.sleep(0.4)

    vix_by_date = {r[0]: r[4] for r in hist.get("^VIX", [])}
    # 11-21 Ben: 원/달러(KRW=X) 일봉 종가는 서울 장 마감 고시라 뉴욕 마감 호가보다 하루 뒤처짐(11-21 1,334.79 vs 실제 1,346).
    # 일봉은 지표 계산용으로 두고, 화면에 쓰는 fx·시세 표의 원/달러 현재가만 meta 최신 호가로 덮는다.
    fx_live = {}
    try:
        m = yahoo_meta("KRW=X")
        p, pc = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
        if p:
            fx_live = {"usdkrw": round(p, 2), "prev": round(pc, 2) if pc else None,
                       "chg": round((p / pc - 1) * 100, 2) if pc else None,
                       "src": "yahoo", "at": m.get("regularMarketTime")}
            if "KRW=X" in symbols:
                symbols["KRW=X"]["price"] = fx_live["usdkrw"]
                symbols["KRW=X"]["live"] = True
                if pc:
                    symbols["KRW=X"]["prev"] = fx_live["prev"]
                    symbols["KRW=X"]["chg"] = fx_live["chg"]
            print("fx live", fx_live["usdkrw"], fx_live["chg"], flush=True)
    except Exception as e:  # noqa
        print("fx meta fail", e, flush=True)
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
    # BDC(사모대출) ETF BIZD: 1년 고점 대비 (11-18 Ben, −15%↓은 과거 바닥 근처라 '바닥 참고' 배지)
    try:
        b = [r[5] for r in yahoo("BIZD", "2y")]
        macro["bizd"] = {"v": round(b[-1], 2), "dd1y": round((b[-1] / max(b[-252:]) - 1) * 100, 1)}
    except Exception as e:  # noqa
        print("bizd fail", e, flush=True)
    # 채권 변동성 MOVE (11-21 Ben, 참고용·판정 미반영). 3년 백분위 90%↑ + VIX 25 미만 = '채권만 불안' 배지 (검증: backtest/MOVE_SKEW_기간프리미엄_검증_20261121.md)
    try:
        mv = [(r[0], r[4]) for r in yahoo("^MOVE", "5y")]
        w = [x[1] for x in mv[-756:]]
        macro["move"] = {"v": round(mv[-1][1], 1), "date": mv[-1][0], "pct3y": round(sum(x <= w[-1] for x in w) / len(w) * 100),
                         "spark": [round(x[1], 1) for x in mv[-520:]]}
    except Exception as e:  # noqa
        print("move fail", e, flush=True)
    # WTI 유가 (11-21 Ben, 거시 점검 보조). 3년(756거래일) 백분위로 높음/보통/낮음 판정 + 배럴 가격·3년 평균·범위·2년 추이
    try:
        bars = hist.get("CL=F") or yahoo("CL=F", "5y")
        c = [r[4] for r in bars]
        w = c[-756:]
        v, d = c[-1], bars[-1][0]
        chg = (c[-1] / c[-2] - 1) * 100 if len(c) > 1 else None
        try:   # 일봉에 아직 없는 더 새로운 호가만 덮는다(스파크라인·백분위와 숫자를 맞추기 위해)
            mm = yahoo_meta("CL=F")
            mp, mpv = mm.get("regularMarketPrice"), mm.get("chartPreviousClose") or mm.get("previousClose")
            mt = mm.get("regularMarketTime")
            md = datetime.fromtimestamp(mt, tz=timezone.utc).strftime("%Y-%m-%d") if mt else None
            if mp and mpv and md and md > d:
                v, d, chg = float(mp), md, (mp / mpv - 1) * 100
        except Exception as e:  # noqa
            print("wti meta fail", e, flush=True)
        p3 = sum(1 for x in w if x <= v) / len(w) * 100
        macro["wti"] = {"v": round(v, 2), "date": d, "chg": round(chg, 2) if chg is not None else None,
                        "avg3y": round(sum(w) / len(w), 2), "min3y": round(min(w), 2), "max3y": round(max(w), 2),
                        "pct3y": round(p3), "status": "높음" if p3 >= 70 else "낮음" if p3 <= 30 else "보통",
                        "avg_vs": round((v / (sum(w) / len(w)) - 1) * 100, 1),
                        "spark": [round(x, 2) for x in c[-520:]]}
        print("wti", macro["wti"]["v"], macro["wti"]["status"], macro["wti"]["pct3y"], flush=True)
    except Exception as e:  # noqa
        print("wti fail", e, flush=True)
    # 10년 실질금리 TIPS (11-21 Ben, 거시 점검 보조). 명목 10년물 − 기대인플레. 3년(756거래일) 백분위로 높음/보통/낮음
    try:
        tp = fred("DFII10", "2003-01-01")
        if len(tp) > 1:
            v, d = tp[-1][1], tp[-1][0]
            pv = tp[-2][1]
            w = [x[1] for x in tp[-756:]]
            p3 = sum(1 for x in w if x <= v) / len(w) * 100
            sp = tp[-520:]
            macro["tips10"] = {"v": round(v, 2), "date": d, "prev": round(pv, 2),
                              "diff_bp": round((v - pv) * 100),
                              "avg3y": round(sum(w) / len(w), 2), "min3y": round(min(w), 2), "max3y": round(max(w), 2),
                              "pct3y": round(p3), "status": "높음" if p3 >= 70 else "낮음" if p3 <= 30 else "보통",
                              "spark": [round(x[1], 2) for x in sp], "spark_dates": [sp[0][0], sp[-1][0]]}
            print("tips10", macro["tips10"]["v"], macro["tips10"]["status"], macro["tips10"]["pct3y"], len(tp), flush=True)
        else:
            print("tips10 no rows", flush=True)
    except Exception as e:  # noqa
        print("tips10 fail", e, flush=True)
    # 중앙은행 금 매입 (11-22 Ben, 거시 점검 보조). 외부 사이트가 잠시 막혀도 전체 빌드는 계속되게 지난 값을 유지한다
    try:
        macro["cb_gold"] = cb_gold()
        print("cb_gold", macro["cb_gold"]["latest_month"], macro["cb_gold"]["latest_net_t"],
              macro["cb_gold"]["cum_3y_t"], flush=True)
    except Exception as e:  # noqa
        old = (prev_market.get("macro") or {}).get("cb_gold")
        if old:
            old["stale"] = True
            macro["cb_gold"] = old
            print("cb_gold fail(지난 값 유지)", e, flush=True)
        else:
            macro["cb_gold"] = None
            print("cb_gold fail", e, flush=True)
    # 11-23 Ben: '바닥 밸류에이션 (참고)' — S&P 500 선행 PER. 외부 사이트가 막혀도 전체 빌드는 계속(지난 값 유지 → 없으면 null)
    # 코스피 PBR: KRX 정보데이터시스템이 2025-12 개편 뒤 회원 로그인 필수라 무료·무인증 수집 경로가 없다.
    # 네이버·다음 지수 페이지에도 PBR 값이 없어, 소스를 확보하기 전까지는 null로 두고 화면에서도 그리지 않는다.
    try:
        old = (prev_market.get("macro") or {}).get("valuation") or {}
        oldpe = old.get("sp500_forward_pe") or {}
        # 15분마다 도는 워크플로가 외부 사이트를 과하게 호출하지 않게, 같은 UTC 날짜에 받은 값은 그날 동안 재사용한다(원본도 하루 1회 갱신)
        if oldpe.get("v") is not None and str(oldpe.get("updated") or "")[:10] == now.strftime("%Y-%m-%d"):
            macro["valuation"] = old
            print("valuation cached", oldpe["v"], oldpe.get("date"), flush=True)
        else:
            pe = sp500_forward_pe()
            macro["valuation"] = {"sp500_forward_pe": pe, "kospi_pbr": None}
            print("valuation sp500 fwd", pe["v"], pe["date"], pe["basis"], flush=True)
    except Exception as e:  # noqa
        old = (prev_market.get("macro") or {}).get("valuation")
        if old and (old.get("sp500_forward_pe") or {}).get("v") is not None:
            old["sp500_forward_pe"]["stale"] = True
            macro["valuation"] = old
            print("valuation fail(지난 값 유지)", e, flush=True)
        else:
            macro["valuation"] = None
            print("valuation fail", e, flush=True)
    print("macro done", flush=True)
    fng = cnn_fng()
    print("fng", fng, flush=True)
    try:
        over = oversold_odds(hist, fng)
        print("oversold", over["current"]["mode"], f"{over['current']['vix_min']:g}/{over['current']['rsi_max']:g}",
              [(x["sym"], x["win"].get("20"), x["signals"]) for x in over["current"]["symbols"]], flush=True)
    except Exception as e:  # noqa
        over = None
        print("oversold fail", e, flush=True)
    try:
        import sentiment as SENT
        sent = SENT.collect(DATA, fred, now)
    except Exception as e:  # noqa
        sent = {"errors": [f"sentiment: {e}"]}
    print("sentiment", {k: v for k, v in sent.items() if k in ("errors", "weeks_recorded")}, flush=True)

    # 시총 1~12위 (11-21 Ben). quote 실패 시 지난 시장 파일의 순위로 폴백하고 화면은 기존 목록으로 되돌아간다
    bt = None
    try:
        if bt_quotes:
            bt = bigtech_rank(bt_quotes, hist, symbols, prev_market.get("bigtech"), now)
            if bt_err:
                bt["err"] = bt_err
            print("bigtech", [f"{r['rank']}.{r['sym']}" for r in bt["rows"]], flush=True)
    except Exception as e:  # noqa
        print("bigtech fail", e, flush=True)
    # 11-23 Ben: 유사 폭락장 카드용 궤적 (최근 2년 고점 이후 QQQ 하락률). macro·VIX가 다 모인 뒤에 계산한다
    try:
        crash_cur = crash_track(hist["QQQ"], hist.get("^VIX"), macro) if "QQQ" in hist else None
        if crash_cur:
            print("crash_track", crash_cur["peak_date"], crash_cur["days"], crash_cur["dd"], crash_cur["live"], flush=True)
    except Exception as e:  # noqa
        crash_cur = None
        print("crash_track fail", e, flush=True)
    market = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fx": fx_live or {"usdkrw": symbols.get("KRW=X", {}).get("price")},
        "symbols": symbols, "macro": macro, "fng": fng, "sentiment": sent, "errors": errors,
        "oversold": over, "bigtech": bt, "crash_track": crash_cur,
        "snapshot": False,
    }
    with open(os.path.join(DATA, "market.json"), "w", encoding="utf-8") as f:
        json.dump(market, f, ensure_ascii=False, separators=(",", ":"))

    # 차트 팝업용 일봉 (최근 960거래일 종가(3년 + 200일선 계산분), 날짜는 일수 차이로 압축). 시세 탭에서 종목을 누를 때만 불러옴
    charts = {}
    for sym, rows in hist.items():
        rr = rows[-960:]
        if len(rr) < 2:
            continue
        d0 = datetime.strptime(rr[0][0], "%Y-%m-%d")
        dd = [(datetime.strptime(r[0], "%Y-%m-%d") - d0).days for r in rr]
        charts[sym] = {"d0": rr[0][0], "dd": [dd[0]] + [dd[i] - dd[i - 1] for i in range(1, len(dd))],
                       "c": [float(f"{r[4]:.5g}") if r[4] < 1000 else round(r[4], 1) for r in rr]}
        # 주봉(ISO 주 마지막 거래일 종가) 최근 320주: 5년 + 40주선 계산분 (11-14 Ben: 40주선 장기 차트)
        wk = {}
        for r in rows:
            wk[datetime.strptime(r[0], "%Y-%m-%d").isocalendar()[:2]] = (r[0], r[4])
        ws = [wk[k] for k in sorted(wk)][-320:]
        if len(ws) >= 2:
            w0 = datetime.strptime(ws[0][0], "%Y-%m-%d")
            wd = [(datetime.strptime(x[0], "%Y-%m-%d") - w0).days for x in ws]
            charts[sym]["w"] = {"d0": ws[0][0], "dd": [wd[0]] + [wd[i] - wd[i - 1] for i in range(1, len(wd))],
                                "c": [float(f"{x[1]:.5g}") if x[1] < 1000 else round(x[1], 1) for x in ws]}
    with open(os.path.join(DATA, "charts.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": market["generated"], "s": charts}, f, ensure_ascii=False, separators=(",", ":"))

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
