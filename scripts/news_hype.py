#!/usr/bin/env python3
"""테마 광풍 + '이번엔 다르다' 보도 감지 — Ben 2026-11-18 요청, 과열 경고 배지용(매매 판정 미반영).

구글 뉴스 RSS(키 없음). 제목 기준 두 가지를 셈(중복 제목 제거).
- 물결(wave): 테마 단어(AI·반도체·코인·2차전지·메타버스 …) + 광풍·열풍·광기·불기둥 / mania·frenzy·craze·euphoria
- 이번엔 다르다(diff): '이번엔 다르다'·'거품 아니다'·'새로운 패러다임' / "this time is different"·"not a bubble"·"new paradigm"
- live(days): 최근 N일 건수·제목 (sentiment.collect에서 호출)
- 직접 실행: 2012-01 이후 월별 건수 → QQQ·SOXX·비트코인 이후 1년 고점까지 개월·최대 하락 비교 → data/news_hype_study.json
"""
import json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
QUERIES = [
    ("ko", "AI 광풍"), ("ko", "AI 열풍 주식"), ("ko", "반도체 광풍"), ("ko", "반도체 열풍 주식"), ("ko", "코인 광풍"), ("ko", "2차전지 광풍"),
    ("ko", "이번엔 다르다 주식"), ("ko", "거품 아니다 주식"),
    ("en", "AI stocks frenzy"), ("en", "AI mania stocks"), ("en", "chip stocks frenzy"), ("en", "crypto mania"),
    ("en", '"this time is different" stocks'), ("en", '"not a bubble" stocks'),
]
THEME = {"ko": re.compile(r"AI|인공지능|챗GPT|엔비디아|반도체|HBM|코인|비트코인|가상\s*화폐|가상\s*자산|2차\s*전지|이차전지|배터리|메타버스|NFT|로봇|양자|원전|바이오|빅테크|나스닥|주식|증시|코스피"),
         "en": re.compile(r"\bAI\b|artificial intelligence|nvidia|chip|semiconductor|crypto|bitcoin|metaverse|nft|quantum|tech|nasdaq|stock|market|dot-?com", re.I)}
WAVE = {"ko": re.compile(r"광풍|열풍|광기|불기둥|폭주|쏠림|묻지\s*마|포모|FOMO", re.I),
        "en": re.compile(r"mania|frenzy|craze|euphoria|fomo|gold rush", re.I)}
DIFF = {"ko": re.compile(r"이번\s*엔\s*다르|이번\s*에는\s*다르|이번\s*엔\s*달라|이번\s*은\s*다르|거품\s*아니|버블\s*아니|버블\s*아냐|거품\s*아냐|새로운\s*패러다임|신\s*경제|닷컴과\s*다르"),
        "en": re.compile(r"this time (is|it'?s) different|not a bubble|isn'?t a bubble|no bubble|new paradigm|new era|unlike (the )?dot-?com", re.I)}
SKEPTIC = re.compile(r"경고|우려|붕괴|폭락|터지|꺼지|warn|crash|burst|collapse", re.I)   # '거품 아니다?' 반박·경고 기사도 같이 걸려서 참고로만 셈
HL = {"ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}, "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"}}

# 과거 사례(수집이 닿지 않는 1996~2011 포함). 신호 = '광풍·이번엔 다르다'가 대중 매체 전면에 나온 시점. lag = 고점까지 개월(음수면 고점 뒤).
CASES = [
    {"sig": "1996-12", "what": "그린스펀 '비이성적 과열' 경고", "peak": "2000-03 나스닥", "lag": 39, "after": "−78% (2002-10)", "kind": "경고가 너무 이름"},
    {"sig": "1999-09", "what": "『Dow 36,000』 출간, '신경제' 보도", "peak": "2000-03 나스닥", "lag": 6, "after": "−78%"},
    {"sig": "1999-12", "what": "타임 올해의 인물 제프 베이조스", "peak": "2000-03 나스닥", "lag": 3, "after": "−78%"},
    {"sig": "2000-01", "what": "AOL·타임워너 합병(닷컴 정점 거래)", "peak": "2000-03 나스닥", "lag": 2, "after": "−78%"},
    {"sig": "2017-12", "what": "비트코인 광풍·CME 선물 상장·'블록체인' 개명주", "peak": "2017-12 비트코인", "lag": 0, "after": "−84% (2018-12)"},
    {"sig": "2021-01", "what": "게임스톱·ARK '혁신은 다르다'", "peak": "2021-02 ARKK", "lag": 1, "after": "−80% (2022-12)"},
    {"sig": "2021-04", "what": "코인베이스 상장, 국내 '코인 광풍'", "peak": "2021-04 비트코인(1차)", "lag": 0, "after": "−50%대 (2021-07)"},
    {"sig": "2021-10", "what": "페이스북→메타 개명, 메타버스 광풍", "peak": "2021-11 QQQ", "lag": 1, "after": "−35% (2022-12)"},
    {"sig": "2023-07", "what": "2차전지 광풍(에코프로 150만원)", "peak": "2023-07 에코프로", "lag": 0, "after": "2개월 만에 −42%"},
    {"sig": "2023-05", "what": "AI 광풍(엔비디아 실적 쇼크, '이번엔 다르다')", "peak": "확인 안 됨", "lag": None, "after": "3년 넘게 상승 지속(중간 −20%대 조정)", "kind": "반례"},
]


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def classify(lang, title):
    if not THEME[lang].search(title):
        return None
    w, d = bool(WAVE[lang].search(title)), bool(DIFF[lang].search(title))
    if not (w or d):
        return None
    return {"wave": w, "diff": d, "skeptic": bool(SKEPTIC.search(title))}


def search(lang, q, after=None, before=None, when=None):
    qq = q + (f" after:{after}" if after else "") + (f" before:{before}" if before else "") + (f" when:{when}" if when else "")
    root = ET.fromstring(_get("https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": qq, **HL[lang]})))
    out = []
    for it in root.iter("item"):
        title = re.sub(r"\s+-\s+[^-]+$", "", (it.findtext("title") or "").strip())   # 끝의 '- 언론사' 제거
        c = classify(lang, title)
        if not c:
            continue
        try:
            d = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except Exception:  # noqa
            d = None
        out.append({"title": title, "date": d, "lang": lang, **c})
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
            print("news_hype fail", q, e, file=sys.stderr)
        time.sleep(0.3)
    return out


def _count(arts):
    return {"n": len(arts), "wave": sum(a["wave"] for a in arts), "diff": sum(a["diff"] for a in arts),
            "ko": sum(a["lang"] == "ko" for a in arts), "en": sum(a["lang"] == "en" for a in arts)}


def live(days=30, data_dir="data"):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    arts = [a for a in collect(when=f"{days}d") if not a["date"] or a["date"] >= since]
    arts.sort(key=lambda a: (a["diff"], a["date"] or ""), reverse=True)
    out = {"days": days, **_count(arts), "titles": [{"t": a["title"][:90], "d": a["date"], "x": "diff" if a["diff"] else "wave"} for a in arts[:6]],
           **_study_summary(data_dir)}
    past = out.get("recent_n") or []
    if len(past) >= 12:   # 월별 연구와 같은 기준: 직전 24개월 대비 상위 10% + 3건 이상이면 과열 감시
        out["pct24"] = round(sum(v < out["n"] for v in past) / len(past) * 100)
        out["hot"] = out["pct24"] >= 90 and out["n"] >= 3
    return out


def _study_summary(data_dir):
    try:
        with open(os.path.join(data_dir, "news_hype_study.json"), encoding="utf-8") as f:
            S = json.load(f)
    except Exception:  # noqa
        return {"cases": CASES}
    ser = S.get("series", [])
    return {"cut": S.get("cut"), "from": S.get("from"), "groups": S.get("groups"), "cases": CASES,
            "top_months": [r["m"] for r in ser if r.get("hot")], "recent_n": [r["n"] for r in ser[-25:-1]]}


def study():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import bisect, statistics as st, build_data as B
    px = {}
    for s in ("QQQ", "SOXX", "BTC-USD"):
        rows = B.yahoo(s, "max"); px[s] = ([r[0] for r in rows], [r[5] for r in rows])
    start = os.environ.get("HYPE_FROM", "2012-01-01")
    months, d = [], datetime.fromisoformat(start)
    while d < datetime.now():
        nd = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        months.append((d.date().isoformat(), nd.date().isoformat())); d = nd
    def prices(row, b):
            for s, (ds, p) in px.items():
                i = bisect.bisect_left(ds, b) - 1
                if i < 0:
                    continue
                k = {"QQQ": "q", "SOXX": "s", "BTC-USD": "b"}[s]
                hi = max(p[max(0, i - 251):i + 1])
                row[k + "dd"] = round((p[i] / hi - 1) * 100, 1)
                fut = p[i:i + 253]
                if len(fut) > 1:
                    j = max(range(len(fut)), key=lambda t: fut[t])
                    row[k + "pk"] = round(j / 21, 1)                                    # 이후 1년 안 최고점까지 개월
                    row[k + "up"] = round((fut[j] / p[i] - 1) * 100, 1)                 # 그 고점까지 추가 상승
                    row[k + "mdd"] = round((min(fut[j:]) / fut[j] - 1) * 100, 1) if j < len(fut) - 1 else 0.0   # 그 고점 뒤 1년 창 안 최대 하락
                for h, n in (("f6", 126), ("f12", 252)):
                    row[k + h] = round((p[i + n] / p[i] - 1) * 100, 1) if i + n < len(p) else None
    OUT = "data/news_hype_study.json"
    try:   # 이어 하기: 작업 시간 제한에 걸려도 다음 실행이 남은 달부터
        with open(OUT, encoding="utf-8") as f:
            done = {r["m"]: r for r in json.load(f).get("series", []) if r.get("final")}
    except Exception:  # noqa
        done = {}
    t0 = time.time(); series = []
    def dump(extra=None):
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"partial": True, "series": series, **(extra or {})}, f, ensure_ascii=False, indent=0)
    for a, b in months:
        if a[:7] in done:
            r = done[a[:7]]; prices(r, b); series.append(r)   # 기사 수는 재사용, 가격 지표만 다시 계산
            continue
        if time.time() - t0 > 280 * 60:
            dump(); print("time limit, partial saved", flush=True); return
        arts = [x for x in collect(after=a, before=b) if not x["date"] or a <= x["date"] < b]
        row = {"m": a[:7], **_count(arts), "titles": [x["title"][:80] for x in sorted(arts, key=lambda x: -x["diff"])[:4]]}
        prices(row, b)
        row["final"] = b <= datetime.now().date().isoformat()
        series.append(row); print(row["m"], row["n"], row["wave"], row["diff"], row.get("qdd"), flush=True)
        dump()
    # 언론 기사 수 자체가 해마다 늘어 절대 건수는 최근으로 쏠림 → 직전 24개월 대비 위치(롤링 상위 10%)로 '과열 달'을 정함
    for i, r in enumerate(series):
        past = [x["n"] for x in series[max(0, i - 24):i]]
        r["pct24"] = round(sum(v < r["n"] for v in past) / len(past) * 100) if len(past) >= 12 else None
        r["hot"] = bool(r["pct24"] is not None and r["pct24"] >= 90 and r["n"] >= 3)
    def grp(f):
        g = [r for r in series if f(r)]
        o = {"months": len(g)}
        for k in ("qdd", "qpk", "qup", "qmdd", "qf6", "qf12", "spk", "smdd", "sf12", "bpk", "bmdd", "bf12"):
            v = [r[k] for r in g if r.get(k) is not None]
            o[k] = round(st.mean(v), 1) if v else None
        q = [r for r in g if r.get("qmdd") is not None]
        o["q_mdd20"] = round(sum(r["qmdd"] <= -20 for r in q) / len(q) * 100) if q else None   # 1년 안 고점 뒤 −20% 이상 하락 비율
        return o
    ns = sorted(r["n"] for r in series)
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "from": start[:7], "queries": QUERIES,
           "cut": max(3, ns[int(len(ns) * 0.9)]), "cases": CASES, "series": series,
           "groups": {"과열 달": grp(lambda r: r["hot"]), "이번엔 다르다 있음": grp(lambda r: r["diff"] >= 1), "전체": grp(lambda r: True)}}
    with open("data/news_hype_study.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=0)
    print(json.dumps({k: res[k] for k in ("cut", "groups")}, ensure_ascii=False))


if __name__ == "__main__":
    study()
