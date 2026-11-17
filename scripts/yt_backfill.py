#!/usr/bin/env python3
"""유튜브 댓글 심리 과거 검증 (GitHub Actions 수동/브랜치 실행).

1) 수집(이어받기 가능): 후보 채널마다 2019-07 이후 업로드 영상 중 주(월~일)별 댓글 많은 일반 영상 2개 →
   관련도순 댓글 100개 중 업로드 후 10일 안 댓글만 → 후보 단어 조합별 개수를 data/yt_backfill_raw.json에 저장.
   쿼터: 검색 100/채널(1회), 목록·영상정보·댓글 각 1. 예산 YT_BUDGET(기본 9300) 넘거나 quotaExceeded면 저장 후 중단.
2) 분석: QQQ 주간 낙폭·최근 4주 수익·이후 수익과 비교 → data/yt_study.json
"""
import json, os, statistics as st, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yt_lexicon as L

CANDS = ["디벨롭몽", "삼프로TV", "슈카월드", "소수몽키", "전인구경제연구소", "김작가 TV", "월가아재의 과학적 투자", "올랜도 킴 미국주식", "박곰희TV"]
START = "2019-07-01"
RAW = "data/yt_backfill_raw.json"
OUT = "data/yt_study.json"
KEY = os.environ.get("YOUTUBE_API_KEY")
BUDGET = int(os.environ.get("YT_BUDGET", "9300"))
used = 0


class Quota(Exception):
    pass


def api(path, cost=1, **q):
    global used
    if used + cost > BUDGET:
        raise Quota("budget")
    q["key"] = KEY
    url = f"https://www.googleapis.com/youtube/v3/{path}?" + urllib.parse.urlencode(q)
    for i in range(3):
        try:
            used += cost
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "invest-dashboard/1.0"}), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if "quotaExceeded" in body or "dailyLimitExceeded" in body:
                raise Quota(body[:200])
            if e.code in (403, 404) and ("commentsDisabled" in body or "videoNotFound" in body or "forbidden" in body.lower()):
                return None
            if i == 2:
                raise
            time.sleep(2)
        except Exception:  # noqa
            if i == 2:
                raise
            time.sleep(2)


def iso_dur(s):
    import re
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def wk(dt):
    mon = (dt - timedelta(days=dt.weekday())).date()
    return mon.isoformat()


def resolve(name, C):
    if C.get("id"):
        return
    j = api("search", 100, part="snippet", type="channel", q=name, maxResults=5, regionCode="KR")
    items = j.get("items", [])
    core = name.replace(" ", "").lower()[:3]
    pick = next((it for it in items if core in it["snippet"]["title"].replace(" ", "").lower()), items[0] if items else None)
    if not pick:
        raise ValueError(f"채널 못 찾음 {name}")
    cid = pick["snippet"]["channelId"]
    ch = api("channels", part="snippet,statistics,contentDetails", id=cid)["items"][0]
    C.update({"id": cid, "title": ch["snippet"]["title"], "subs": int(ch["statistics"].get("subscriberCount", 0)),
              "videos": int(ch["statistics"].get("videoCount", 0)), "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"],
              "search_alts": [it["snippet"]["title"] for it in items]})


def list_uploads(C):
    if C.get("picked"):
        return
    vids, tok = [], None
    while True:
        q = {"part": "contentDetails", "playlistId": C["uploads"], "maxResults": 50}
        if tok:
            q["pageToken"] = tok
        j = api("playlistItems", **q)
        stop = False
        for it in j.get("items", []):
            p = it["contentDetails"].get("videoPublishedAt")
            if not p:
                continue
            if p[:10] < START:
                stop = True; continue
            vids.append(it["contentDetails"]["videoId"])
        tok = j.get("nextPageToken")
        if stop or not tok:
            break
    info = []
    for i in range(0, len(vids), 50):
        j = api("videos", part="contentDetails,statistics,snippet", id=",".join(vids[i:i + 50]), maxResults=50)
        for v in j.get("items", []):
            dur = iso_dur(v["contentDetails"].get("duration"))
            cc = int(v["statistics"].get("commentCount", 0) or 0)
            if dur >= 180 and cc > 0 and v["snippet"].get("liveBroadcastContent", "none") == "none":
                info.append((v["snippet"]["publishedAt"], v["id"], cc))
    byw = defaultdict(list)
    for p, vid, cc in info:
        byw[wk(datetime.fromisoformat(p.replace("Z", "+00:00")))].append((cc, vid, p))
    C["picked"] = {w: [(vid, p) for cc, vid, p in sorted(v, reverse=True)[:2]] for w, v in byw.items()}
    C["n_uploads"] = len(vids); C["n_regular"] = len(info)
    C.setdefault("weeks", {}); C.setdefault("done", [])


def fetch_comments(R):
    """주 단위로 최근부터 채널을 번갈아 가며 → 쿼터에서 멈춰도 채널 간 기간이 고르게 남음"""
    tasks = []
    for name, C in R["channels"].items():
        done = set(C.get("done", []))
        for w, vs in C.get("picked", {}).items():
            tasks += [(w, name, vid, p) for vid, p in vs if vid not in done]
    tasks.sort(reverse=True)
    for w, name, vid, p in tasks:
        C = R["channels"][name]
        j = api("commentThreads", part="snippet", videoId=vid, maxResults=100, order="relevance", textFormat="plainText")
        p0 = datetime.fromisoformat(p.replace("Z", "+00:00"))
        W = C["weeks"].setdefault(w, {"n": 0, "combo": {}})
        for c in (j or {}).get("items", []):
            s = c["snippet"]["topLevelComment"]["snippet"]
            if datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00")) > p0 + timedelta(days=10):
                continue
            W["n"] += 1
            h = L.hits(s.get("textDisplay", ""))
            if h:
                k = "|".join(sorted(h)); W["combo"][k] = W["combo"].get(k, 0) + 1
        C["done"].append(vid)


def collect():
    try:
        with open(RAW, encoding="utf-8") as f:
            R = json.load(f)
    except Exception:  # noqa
        R = {"channels": {}}
    R.setdefault("log", [])
    msg = "complete"
    try:
        for name in CANDS:
            C = R["channels"].setdefault(name, {})
            resolve(name, C); list_uploads(C)
            print(name, C.get("title"), C.get("subs"), "regular", C.get("n_regular"), "units", used, flush=True)
        fetch_comments(R)
    except Quota as e:
        msg = f"quota stop: {e}"
    R["log"].append({"at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "units": used, "result": msg})
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, separators=(",", ":"))
    print(msg, "units", used)
    return R


# ---------- 분석 ----------
def spearman(a, b):
    pr = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pr) < 20:
        return None
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
        for k, i in enumerate(o):
            r[i] = k
        return r
    ra, rb = rank([p[0] for p in pr]), rank([p[1] for p in pr])
    try:
        return round(st.correlation(ra, rb), 3)
    except Exception:  # noqa
        return None


def qqq_weekly():
    import build_data as B
    rows = B.yahoo("QQQ", "max")
    ds = [r[0] for r in rows]; px = [r[5] for r in rows]
    import bisect
    def at(d):  # d 이전 마지막 종가 인덱스
        i = bisect.bisect_right(ds, d) - 1
        return i
    out = {}
    mon = datetime.fromisoformat(START)
    while mon.date().isoformat() <= ds[-1]:
        w = mon.date().isoformat(); fri = (mon + timedelta(days=6)).date().isoformat()
        i = at(fri)
        hi = max(px[max(0, i - 251):i + 1])
        r = {"dd": round((px[i] / hi - 1) * 100, 1), "r4": round((px[i] / px[i - 20] - 1) * 100, 1)}
        for k, h in (("f4", 20), ("f13", 63), ("f26", 126)):
            r[k] = round((px[i + h] / px[i] - 1) * 100, 1) if i + h < len(px) else None
        out[w] = r
        mon += timedelta(days=7)
    return out


def stage_counts(W, lex):
    c = Counter()
    for k, n in W["combo"].items():
        s = L.stage_of(set(k.split("|")), lex)
        if s:
            c[s] += n
    return c


def analyze(R, lex=None):
    lex = lex or L.STAGES
    Q = qqq_weekly()
    weeks = sorted(Q)
    pooled = {w: {"n": 0, "combo": Counter()} for w in weeks}
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "lexicon": lex, "channels": {}, "log": R.get("log", [])[-5:]}
    for name, C in R["channels"].items():
        if not C.get("weeks"):
            res["channels"][name] = {"title": C.get("title"), "subs": C.get("subs"), "weeks": 0}
            continue
        sc, n_all, m_all = {}, 0, 0
        for w, W in C["weeks"].items():
            if w in pooled:
                pooled[w]["n"] += W["n"]; pooled[w]["combo"].update(W["combo"])
            c = stage_counts(W, lex); sc[w] = L.score(c); n_all += W["n"]; m_all += sum(c.values())
        xs = [sc.get(w) for w in weeks]
        res["channels"][name] = {"title": C.get("title"), "subs": C.get("subs"), "regular_videos": C.get("n_regular"), "weeks": len(C["weeks"]),
                                 "comments": n_all, "match_rate": round(m_all / n_all * 100, 1) if n_all else None,
                                 "rho_dd": spearman(xs, [Q[w]["dd"] for w in weeks]), "rho_r4": spearman(xs, [Q[w]["r4"] for w in weeks]),
                                 "rho_f13": spearman(xs, [Q[w]["f13"] for w in weeks])}
    series = []
    for w in weeks:
        c = stage_counts(pooled[w], lex)
        series.append({"w": w, "n": pooled[w]["n"], **{k: c.get(k, 0) for k in L.WEIGHT}, "score": L.score(c), **Q[w]})
    # 4주 이동평균(잡음 감소)
    for i, s in enumerate(series):
        v = [x["score"] for x in series[max(0, i - 3):i + 1] if x["score"] is not None]
        s["s4"] = round(sum(v) / len(v), 1) if len(v) >= 2 else None
    res["series"] = series
    for key in ("score", "s4"):
        xs = [s[key] for s in series]
        res[f"rho_{key}"] = {k: spearman(xs, [s[k] for s in series]) for k in ("dd", "r4", "f4", "f13", "f26")}
    # 점수 구간별 이후 QQQ 수익 (전체 표본 분위, 사후 기준)
    vals = sorted(s["s4"] for s in series if s["s4"] is not None)
    if len(vals) > 40:
        lo, hi = vals[len(vals) // 10], vals[len(vals) * 9 // 10]
        def grp(f):
            g = [s for s in series if s["s4"] is not None and f(s["s4"])]
            row = {"n": len(g), "dd": round(st.mean(x["dd"] for x in g), 1)}
            for k in ("f4", "f13", "f26"):
                r = [x[k] for x in g if x[k] is not None]
                row[k] = round(st.mean(r), 1) if r else None; row["w" + k] = round(sum(x > 0 for x in r) / len(r) * 100) if r else None
            return row
        res["buckets"] = {"cut": [lo, hi], "공포 하위10%": grp(lambda v: v <= lo), "중간": grp(lambda v: lo < v < hi), "탐욕 상위10%": grp(lambda v: v >= hi), "전체": grp(lambda v: True)}
    # 사건 시점
    ev = {"2020-03-16": "코로나 급락", "2021-11-15": "2021 고점", "2022-06-13": "2022 1차 저점", "2022-10-10": "2022 바닥",
          "2023-07-17": "2023 반등 고점", "2024-07-08": "2024-07 고점", "2024-08-05": "엔캐리 급락", "2025-04-07": "관세 급락"}
    idx = {s["w"]: s for s in series}
    res["events"] = [{"w": w, "label": lb, **{k: idx[w].get(k) for k in ("score", "s4", "dd", "n")},
                      "pctile": round(sum(v <= idx[w]["s4"] for v in vals) / len(vals) * 100) if idx.get(w, {}).get("s4") is not None and vals else None}
                     for w, lb in ev.items() if w in idx]
    # 단어별: 1000댓글당 빈도와 QQQ 낙폭·최근 4주 수익 상관, 하락장(dd≤−15%) vs 고점권(dd>−3%) 빈도 비
    words = [w for ws in L.CANDIDATES.values() for w in ws]
    kw = {}
    for word in words:
        rate = []
        for s in series:
            n = pooled[s["w"]]["n"]
            h = sum(c for k, c in pooled[s["w"]]["combo"].items() if word in k.split("|"))
            rate.append(h / n * 1000 if n >= 100 else None)
        tot = sum(sum(c for k, c in pooled[w]["combo"].items() if word in k.split("|")) for w in weeks)
        bear = [r for r, s in zip(rate, series) if r is not None and s["dd"] <= -15]
        top = [r for r, s in zip(rate, series) if r is not None and s["dd"] > -3]
        stage = next(k for k, v in L.CANDIDATES.items() if word in v)
        kw[word] = {"stage": stage, "hits": tot, "rho_dd": spearman(rate, [s["dd"] for s in series]), "rho_r4": spearman(rate, [s["r4"] for s in series]),
                    "bear": round(st.mean(bear), 2) if bear else None, "top": round(st.mean(top), 2) if top else None,
                    "lift": round(st.mean(bear) / st.mean(top), 2) if bear and top and st.mean(top) > 0 else None}
    res["keywords"] = kw
    res["weeks_bear"] = sum(s["dd"] <= -15 for s in series); res["weeks_top"] = sum(s["dd"] > -3 for s in series)
    return res


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    if KEY and not os.environ.get("YT_ANALYZE_ONLY"):
        R = collect()
    else:
        with open(RAW, encoding="utf-8") as f:
            R = json.load(f)
    out = analyze(R)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(json.dumps({k: out.get(k) for k in ("rho_score", "rho_s4", "buckets", "events")}, ensure_ascii=False))
    for n, c in out["channels"].items():
        print(n, c)
