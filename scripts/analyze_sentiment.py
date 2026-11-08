#!/usr/bin/env python3
"""인간지표(투자자 심리·레버리지) 검증 → data/sentiment_study.json
과거 데이터가 있는 무료 지표만: FINRA 마진부채(월, 1997~), AAII 강세-약세(주, 1987~),
NAAIM 노출지수(주, 2006~), CBOE 주식 풋콜비율(일, 2006~2019).
각 지표를 '자기 과거 대비 극단(상·하위 10%)'으로 나눠 이후 QQQ·SPY 1·3·6·12개월 수익률과 비교.
수집 실패는 errors에 남김. GitHub Actions 수동 실행."""
import io, json, os, re, statistics as st, sys, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as B

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
HZ = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
ERR = []


def get_bytes(url, headers=None, timeout=40):
    import urllib.request
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def find_link(page_url, pat):
    html = get_bytes(page_url).decode("utf-8", "ignore")
    m = re.findall(r'href="([^"]+)"', html)
    for h in m:
        if re.search(pat, h, re.I):
            if h.startswith("/"):
                from urllib.parse import urljoin
                h = urljoin(page_url, h)
            return h
    raise ValueError(f"링크 못 찾음: {page_url} {pat}")


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, "year") and hasattr(v, "month"):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 60000:  # excel serial
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    s = str(v).strip()
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b-%y", "%B %Y", "%Y-%m", "%b %Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def sheet_rows(data, kind):
    if kind == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        import xlrd
        wb = xlrd.open_workbook(file_contents=data)
        for ws in wb.sheets():
            rows = []
            for i in range(ws.nrows):
                r = []
                for j, cell in enumerate(ws.row(i)):
                    v = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        v = xlrd.xldate.xldate_as_datetime(v, wb.datemode)
                    r.append(v)
                rows.append(r)
            yield ws.name, rows


def num(v):
    try:
        if isinstance(v, str):
            v = v.replace(",", "").replace("%", "").strip()
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- 수집 ----------
def finra_margin():
    url = find_link("https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics", r"\.xlsx?")
    data = get_bytes(url)
    out = {}
    for _, rows in sheet_rows(data, "xlsx" if url.lower().endswith("x") else "xls"):
        for r in rows:
            if not r or len(r) < 2:
                continue
            d = to_date(r[0]); v = num(r[1])
            if d and v and v > 1000:
                out[d.strftime("%Y-%m")] = v
    if len(out) < 100:
        raise ValueError(f"FINRA 행 부족 {len(out)}")
    return out  # 월 → 마진 부채(백만$)


def aaii():
    data = get_bytes("https://www.aaii.com/files/surveys/sentiment.xls", {"Referer": "https://www.aaii.com/sentimentsurvey"})
    out = {}
    for _, rows in sheet_rows(data, "xls"):
        for r in rows:
            if not r or len(r) < 4:
                continue
            d = to_date(r[0]); bull, bear = num(r[1]), num(r[3])
            if d and bull is not None and bear is not None and 0 <= bull <= 1.0 and 0 <= bear <= 1.0:
                out[d.isoformat()] = (bull - bear) * 100
    if len(out) < 200:
        raise ValueError(f"AAII 행 부족 {len(out)}")
    return out  # 주 → 강세-약세 %p


def naaim():
    url = find_link("https://www.naaim.org/programs/naaim-exposure-index/", r"\.xlsx?($|\?)")
    data = get_bytes(url)
    out = {}
    for _, rows in sheet_rows(data, "xlsx" if ".xlsx" in url.lower() else "xls"):
        hdr = None
        for r in rows:
            if not r:
                continue
            if hdr is None and any(isinstance(x, str) and "mean" in x.lower() for x in r):
                hdr = [str(x or "").lower() for x in r]; continue
            if hdr is None:
                continue
            d = to_date(r[0]); k = next((i for i, h in enumerate(hdr) if "mean" in h or "average" in h), 1)
            v = num(r[k]) if k < len(r) else None
            if d and v is not None:
                out[d.isoformat()] = v
        if out:
            break
    if len(out) < 200:
        raise ValueError(f"NAAIM 행 부족 {len(out)}")
    return out  # 주 → 액티브 매니저 주식 노출(%)


def cboe_pc():
    txt = get_bytes("https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv").decode("utf-8", "ignore")
    out = {}
    for line in txt.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 5:
            continue
        d = to_date(f[0]); v = num(f[-1])
        if d and v is not None and 0.1 < v < 3:
            out[d.isoformat()] = v
    if len(out) < 500:
        raise ValueError(f"CBOE 행 부족 {len(out)}")
    return out  # 일 → 주식 풋콜비율


# ---------- 분석 ----------
def price_map(sym):
    rows = B.yahoo(sym, "max")
    return [r[0] for r in rows], [r[5] for r in rows]


def fwd(dates, px, d):
    """d(YYYY-MM-DD) 이후 첫 거래일 기준 수익률 dict"""
    import bisect
    i = bisect.bisect_left(dates, d)
    if i >= len(dates):
        return None
    return {k: ((px[i + h] / px[i] - 1) * 100 if i + h < len(px) else None) for k, h in HZ.items()}


def bucket_study(series, transform, label, lookback, prices, hi_is="과열"):
    """series: {date: value}. transform: 'level' 또는 'yoy'(전년 대비 %). 자기 과거 lookback개 대비 백분위."""
    ks = sorted(series)
    vals = [series[k] for k in ks]
    if transform == "yoy":
        step = 12 if len(ks[0]) == 7 else 52
        ks2, v2 = [], []
        for i in range(step, len(ks)):
            if vals[i - step]:
                ks2.append(ks[i]); v2.append((vals[i] / vals[i - step] - 1) * 100)
        ks, vals = ks2, v2
    pts = []
    for i in range(lookback, len(ks)):
        hist = vals[i - lookback:i]
        pr = sum(x <= vals[i] for x in hist) / len(hist) * 100
        d = ks[i] if len(ks[i]) == 10 else ks[i] + "-28"
        if len(ks[i]) == 7:  # 월 데이터: 다음 달 말 발표 → 발표 시점 기준(약 4주 지연)
            y, m = int(ks[i][:4]), int(ks[i][5:7]); m += 1
            if m > 12: y += 1; m = 1
            d = f"{y:04d}-{m:02d}-28"
        pts.append((d, vals[i], pr))
    res = {"label": label, "transform": transform, "n": len(pts), "start": pts[0][0] if pts else None,
           "end": pts[-1][0] if pts else None, "latest": {"date": pts[-1][0], "value": round(pts[-1][1], 2), "pctile": round(pts[-1][2], 0)} if pts else None,
           "high_means": hi_is, "by_ticker": {}}
    for sym, (dates, px) in prices.items():
        groups = {"하위 10%": [], "중간": [], "상위 10%": [], "전체": []}
        for d, v, pr in pts:
            f = fwd(dates, px, d)
            if not f:
                continue
            g = "하위 10%" if pr <= 10 else "상위 10%" if pr >= 90 else "중간"
            groups[g].append(f); groups["전체"].append(f)
        out = {}
        for g, fs in groups.items():
            row = {"n": len(fs)}
            for k in HZ:
                r = [x[k] for x in fs if x[k] is not None]
                row[k] = round(st.mean(r), 2) if r else None
                row["w" + k] = round(sum(x > 0 for x in r) / len(r) * 100, 0) if r else None
            out[g] = row
        res["by_ticker"][sym] = out
    return res


def main():
    out = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "studies": {}, "errors": []}
    prices = {}
    for s in ("QQQ", "SPY"):
        prices[s] = price_map(s); time.sleep(0.5)
    jobs = [
        ("finra_margin_yoy", finra_margin, "yoy", "FINRA 마진부채 전년 대비 증가율", 120, "과열(빚투 급증)"),
        ("finra_margin_lvl", finra_margin, "level", "FINRA 마진부채 수준", 60, "과열"),
        ("aaii", aaii, "level", "AAII 개인투자자 강세−약세", 260, "과열(낙관)"),
        ("naaim", naaim, "level", "NAAIM 액티브 매니저 노출", 260, "과열(풀베팅)"),
        ("cboe_pc", cboe_pc, "level", "CBOE 주식 풋콜비율", 756, "공포(풋 쏠림)"),
    ]
    cache = {}
    for key, fn, tr, label, lb, hi in jobs:
        try:
            if fn not in cache:
                cache[fn] = fn()
            out["studies"][key] = bucket_study(cache[fn], tr, label, lb, prices, hi)
            print(key, "ok", out["studies"][key]["n"])
        except Exception as e:  # noqa
            out["errors"].append(f"{key}: {type(e).__name__}: {e}"[:300]); print(key, "fail", e)
    os.makedirs("data", exist_ok=True)
    with open("data/sentiment_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
