#!/usr/bin/env python3
"""투자 손실 비극 보도(주식·코인 손실 뒤 극단적 선택) 감지 — Ben 2026-11-18 요청, 바닥 경고 배지용.

구글 뉴스 RSS(키 없음). 국내·해외 검색어로 기사를 모은 뒤 제목에 '비극 단어'와 '투자 단어'가 같이 있는 것만 셈(중복 제목 제거).
- live(days): 최근 N일 건수와 제목 (sentiment.collect에서 호출)
- 직접 실행: 2019-01 이후 월별 건수 → QQQ·비트코인 낙폭·이후 수익과 비교 → data/news_extreme_study.json
"""
import json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
QUERIES = [
    ("ko", "주식 손실 극단적 선택"), ("ko", "코인 손실 극단적 선택"), ("ko", "빚투 극단적 선택"),
    ("ko", "가상화폐 투자 실패 숨진"), ("ko", "주식 투자 실패 숨진 채"),
    ("en", "stock market losses suicide"), ("en", "crypto losses suicide"),
]
TRAGIC = {"ko": re.compile(r"극단\s*적?\s*선택|숨진\s*채|목숨|투신|스스로\s*생"), "en": re.compile(r"suicide|took (his|her|their) own life|killed (himself|herself)", re.I)}
INVEST = {"ko": re.compile(r"주식|코인|비트코인|가상\s*화폐|가상\s*자산|암호\s*화폐|빚투|투자|루나|선물|레버리지|증권"),
          "en": re.compile(r"\bloss(es)?\b|\blost\b|debt|margin call|liquidat|crypto|bitcoin|trader|trading|investor|luna|terra|ftx|robinhood", re.I)}
FOLLOWUP = re.compile(r"lawsuit|sued|settle|trial|drug|fda|patient|depression|소송|합의|임상", re.I)   # 예전 사건 후속 기사 제외
HL = {"ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}, "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"}}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def search(lang, q, after=None, before=None, when=None):
    qq = q + (f" after:{after}" if after else "") + (f" before:{before}" if before else "") + (f" when:{when}" if when else "")
    root = ET.fromstring(_get("https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": qq, **HL[lang]})))
    out = []
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+[^-]+$", "", t)   # 끝의 '- 언론사' 제거
        if TRAGIC[lang].search(title) and INVEST[lang].search(title) and not FOLLOWUP.search(title):
            try:
                d = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
            except Exception:  # noqa
                d = None
            out.append({"title": title, "date": d, "lang": lang, "link": it.findtext("link")})
    return out


def collect(**kw):
    seen, out = set(), []
    for lang, q in QUERIES:
        try:
            for a in search(lang, q, **kw):
                key = re.sub(r"\W", "", a["title"])[:40]
                if key not in seen:
                    seen.add(key); out.append(a)
        except Exception as e:  # noqa
            print("news_extreme fail", q, e, file=sys.stderr)
        time.sleep(0.6)
    return out


def live(days=14, data_dir="data"):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    arts = [a for a in collect(when=f"{days}d") if not a["date"] or a["date"] >= since]
    arts.sort(key=lambda a: a["date"] or "", reverse=True)
    return {"days": days, "count": len(arts), "ko": sum(a["lang"] == "ko" for a in arts), "en": sum(a["lang"] == "en" for a in arts),
            "titles": [{"t": a["title"][:90], "d": a["date"], "l": a["lang"]} for a in arts[:5]], **_study_summary(data_dir)}


def _study_summary(data_dir):
    try:
        with open(os.path.join(data_dir, "news_extreme_study.json"), encoding="utf-8") as f:
            S = json.load(f)
    except Exception:  # noqa
        return {}
    g = S.get("groups", {})
    return {"cut": S.get("cut_top10"), "study": {k: g.get(k) for k in ("상위 10% 달", "전체")},
            "top_months": [r["m"] for r in S.get("series", []) if r["n"] >= (S.get("cut_top10") or 99)]}


def study():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import bisect, statistics as st, build_data as B
    px = {}
    for s in ("QQQ", "BTC-USD"):
        rows = B.yahoo(s, "max"); px[s] = ([r[0] for r in rows], [r[5] for r in rows])
    months = []
    d = datetime(2019, 1, 1)
    while d < datetime.now():
        nd = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        months.append((d.date().isoformat(), nd.date().isoformat())); d = nd
    series = []
    for a, b in months:
        arts = [x for x in collect(after=a, before=b) if not x["date"] or a <= x["date"] < b]
        row = {"m": a[:7], "n": len(arts), "ko": sum(x["lang"] == "ko" for x in arts), "en": sum(x["lang"] == "en" for x in arts),
               "titles": [x["title"][:80] for x in arts[:4]]}
        for s, (ds, p) in px.items():
            i = bisect.bisect_left(ds, b) - 1
            if i < 0:
                continue
            hi = max(p[max(0, i - 251):i + 1])
            k = "q" if s == "QQQ" else "b"
            row[k + "dd"] = round((p[i] / hi - 1) * 100, 1)
            lo_next = min(p[i:i + 64]) if i + 1 < len(p) else p[i]
            row[k + "more"] = round((lo_next / p[i] - 1) * 100, 1)   # 이후 3개월 안 추가 최대 하락
            for h, n in (("f3", 63), ("f6", 126)):
                row[k + h] = round((p[i + n] / p[i] - 1) * 100, 1) if i + n < len(p) else None
        series.append(row); print(row["m"], row["n"], row.get("qdd"), row.get("bdd"), flush=True)
    def grp(f):
        g = [r for r in series if f(r)]
        o = {"months": len(g)}
        for k in ("qdd", "bdd", "qmore", "bmore", "qf3", "qf6", "bf3", "bf6"):
            v = [r[k] for r in g if r.get(k) is not None]
            o[k] = round(st.mean(v), 1) if v else None
        return o
    ns = sorted(r["n"] for r in series)
    cut = max(2, ns[int(len(ns) * 0.9)])
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "queries": QUERIES, "cut_top10": cut, "series": series,
           "groups": {"상위 10% 달": grp(lambda r: r["n"] >= cut), "1건 이상": grp(lambda r: r["n"] >= 1), "0건": grp(lambda r: r["n"] == 0), "전체": grp(lambda r: True)}}
    with open("data/news_extreme_study.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=0)
    print(json.dumps({k: res[k] for k in ("cut_top10", "groups")}, ensure_ascii=False))


if __name__ == "__main__":
    study()
