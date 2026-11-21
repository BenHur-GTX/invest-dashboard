#!/usr/bin/env python3
"""11-20 Ben: 장외(장전·장후·야간 24시간 거래) 시세 + 나스닥·S&P 선물 → data/ext.json

Yahoo chart API meta.fulldayPrice = 야간 거래까지 포함한 최신가(15분 지연 이내).
장외 등락률 = 최신가 / 직전 정규장 가격(regularMarketPrice) − 1.
매매 판정(RSI·200일선·낙폭)은 정규장 종가(market.json) 그대로 쓰고, 이 파일은 화면 표시용.
미국 정규장 시간에는 쓰지 않는다(update-data가 15분마다 정규장 시세를 갱신).
11-21 Ben: 원/달러(KRW=X) meta.regularMarketPrice도 같이 담는다(ext.fx). 일봉 종가는 서울 장 마감
고시라 뉴욕 마감 호가보다 하루 뒤처져서(11-21 1,334.79 vs 실제 1,346) 화면 환율이 어긋났다.
"""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SYMBOLS, DATA, http_get  # noqa: E402

ET = ZoneInfo("America/New_York")
FUT = {"NQ": "NQ=F", "ES": "ES=F"}
FX = "KRW=X"
NAVER_FX = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"   # 하나은행 고시회차 (Yahoo 실패 시 대체)


def session(now):
    """미국 동부시간 기준 세션. pre 04:00~09:30, reg ~16:00, post ~20:00, night 20:00~04:00(일~목 밤), closed 주말"""
    t = now.astimezone(ET); w = t.weekday(); m = t.hour * 60 + t.minute
    if w < 5 and 240 <= m < 570: return "pre"
    if w < 5 and 570 <= m < 960: return "reg"
    if w < 5 and 960 <= m < 1200: return "post"
    if (w in (6, 0, 1, 2, 3) and m >= 1200) or (w in (0, 1, 2, 3, 4) and m < 240): return "night"
    return "closed"


def meta(sym):
    q = urllib.request.quote(sym)
    for host in ("query1", "query2"):
        try:
            j = json.loads(http_get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range=1d&interval=15m&includePrePost=true", tries=2, timeout=15))
            return sym, j["chart"]["result"][0]["meta"]
        except Exception as e:  # noqa
            err = e
    return sym, {"error": repr(err)[:120]}


def r(x, n=4):
    return None if x is None else round(x, n)


def fx_naver():
    """네이버 금융 하나은행 고시(closePrice, fluctuations = 전일 대비) → fx/fx_prev/fx_chg"""
    e = json.loads(http_get(NAVER_FX, tries=2, timeout=15))["exchangeInfo"]
    p = float(str(e.get("closePrice") or e.get("calcPrice")).replace(",", ""))
    d = float(str(e.get("fluctuations") or 0).replace(",", ""))
    if str((e.get("fluctuationsType") or {}).get("name", "")).upper() == "FALLING":
        d = -d
    prev = p - d
    return {"fx": round(p, 2), "fx_prev": round(prev, 2) if prev else None,
            "fx_chg": round(d / prev * 100, 2) if prev else None, "fx_src": "naver"}


def fx_quote(m):
    """원/달러: Yahoo meta 최신 호가 우선, 실패하면 네이버 하나은행 고시"""
    p, pc = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    if p:
        return {"fx": r(p, 2), "fx_prev": r(pc, 2) if pc else None,
                "fx_chg": r((p / pc - 1) * 100, 2) if pc else None, "fx_src": "yahoo"}
    try:
        return fx_naver()
    except Exception as e:  # noqa
        return {"fx_src": "fail", "fx_err": repr(e)[:80]}


def main():
    now = datetime.now(timezone.utc)
    sess = session(now)
    if sess == "reg" and not os.environ.get("FORCE"):
        print("정규장 시간: 건너뜀"); return
    us = [s for s, _, _, cur, src in SYMBOLS if src == "y" and cur == "USD" and not s.startswith("^") and not s.endswith("-USD")]
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(meta, us + list(FUT.values()) + [FX]))
    q, errs = {}, []
    for s in us:
        m = res.get(s, {})
        base, p = m.get("regularMarketPrice"), m.get("fulldayPrice")
        if not base or not p:
            errs.append(s); continue
        q[s] = {"p": r(p), "base": r(base), "chg": r((p / base - 1) * 100, 2)}
    fut = {}
    for k, s in FUT.items():
        m = res.get(s, {})
        p, pc = m.get("regularMarketPrice"), m.get("previousClose") or m.get("chartPreviousClose")
        if p and pc:
            fut[k] = {"p": r(p, 2), "prev": r(pc, 2), "chg": r((p / pc - 1) * 100, 2), "t": m.get("regularMarketTime"),
                      "name": m.get("shortName")}
        else:
            errs.append(s)
    fx = fx_quote(res.get(FX, {}))
    if fx.get("fx_src") == "fail":
        errs.append(FX + ":fx")
    out = {"asof": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sess": sess, "fut": fut, "q": q, **fx, "errors": errs}
    with open(os.path.join(DATA, "ext.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("ok", sess, len(q), "symbols", len(fut), "futures", "fx", fx.get("fx"), fx.get("fx_chg"), fx.get("fx_src"), "errors:", errs)


if __name__ == "__main__":
    main()
