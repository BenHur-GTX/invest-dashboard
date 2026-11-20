#!/usr/bin/env python3
"""11-20 Ben: 장외(장전·장후·야간 24시간 거래) 시세 + 나스닥·S&P 선물 → data/ext.json

Yahoo chart API meta.fulldayPrice = 야간 거래까지 포함한 최신가(15분 지연 이내).
장외 등락률 = 최신가 / 직전 정규장 가격(regularMarketPrice) − 1.
매매 판정(RSI·200일선·낙폭)은 정규장 종가(market.json) 그대로 쓰고, 이 파일은 화면 표시용.
미국 정규장 시간에는 쓰지 않는다(update-data가 15분마다 정규장 시세를 갱신).
"""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SYMBOLS, DATA, http_get  # noqa: E402

ET = ZoneInfo("America/New_York")
FUT = {"NQ": "NQ=F", "ES": "ES=F"}


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


def main():
    now = datetime.now(timezone.utc)
    sess = session(now)
    if sess == "reg" and not os.environ.get("FORCE"):
        print("정규장 시간: 건너뜀"); return
    us = [s for s, _, _, cur, src in SYMBOLS if src == "y" and cur == "USD" and not s.startswith("^") and not s.endswith("-USD")]
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(meta, us + list(FUT.values())))
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
    out = {"asof": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sess": sess, "fut": fut, "q": q, "errors": errs}
    with open(os.path.join(DATA, "ext.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("ok", sess, len(q), "symbols", len(fut), "futures", "errors:", errs)


if __name__ == "__main__":
    main()
