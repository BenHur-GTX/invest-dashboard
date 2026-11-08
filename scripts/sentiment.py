"""인간지표 수집 (build_data에서 호출, 하루 1회 갱신)
- AAII 개인투자자 강세−약세 (주간, 무료)
- 연준 Z.1 가계 증권신용(마진) 전년 대비 (분기, FRED)
- 유튜브 댓글 비관/낙관 키워드 (YOUTUBE_API_KEY 있을 때)
- 네이버 뉴스 공포/탐욕 검색어 주간 기사 수 (NAVER_CLIENT_ID/SECRET 있을 때)
- 금융투자협회 신용융자·예탁금 (DATA_GO_KR_KEY 있을 때)
주간 값은 data/sentiment_hist.json에 쌓아 자기 과거 대비 백분위를 냄(기준선 축적)."""
import io, json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

YT_CHANNELS = ["디벨롭몽"]   # 채널 이름(검색 1회 후 ID 캐시)
YT_NEG = ["손절", "물렸", "망했", "망함", "한강", "사기", "폭망", "깡통", "반대매매", "지옥", "끝났", "살려", "멘붕", "ㅅㅂ", "시발", "씨발", "개같", "좆", "꼴보기", "탈출"]
YT_POS = ["가즈아", "풀매수", "인증", "졸업", "부자", "떡상", "익절", "몰빵", "최고", "감사합니다", "수익"]
NEWS_FEAR = ["반대매매", "개미 눈물", "주식 손실", "패닉셀", "빚투 손실"]
NEWS_GREED = ["TQQQ 수익", "레버리지 ETF 열풍", "서학개미 순매수", "계좌 인증", "빚투 급증"]


def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pctile(hist, v):
    h = [x for x in hist if x is not None]
    return round(sum(x <= v for x in h) / len(h) * 100) if len(h) >= 8 else None


def aaii():
    import xlrd
    data = _get("https://www.aaii.com/files/surveys/sentiment.xls", {"Referer": "https://www.aaii.com/sentimentsurvey"})
    wb = xlrd.open_workbook(file_contents=data)
    pts = []
    for ws in wb.sheets():
        for i in range(ws.nrows):
            r = ws.row(i)
            if len(r) < 4 or r[0].ctype != xlrd.XL_CELL_DATE:
                continue
            try:
                d = xlrd.xldate.xldate_as_datetime(r[0].value, wb.datemode).date().isoformat()
                bull, bear = float(r[1].value), float(r[3].value)
            except (TypeError, ValueError):
                continue
            if 0 <= bull <= 1 and 0 <= bear <= 1:
                pts.append((d, (bull - bear) * 100, bull * 100, bear * 100))
        if pts:
            break
    pts.sort()
    d, v, bu, be = pts[-1]
    hist = [p[1] for p in pts[-261:-1]]
    return {"date": d, "value": round(v, 1), "bull": round(bu, 1), "bear": round(be, 1), "pctile": _pctile(hist, v),
            "spark": [round(p[1], 1) for p in pts[-104:]]}


def fed_margin(fred):
    for sid in ("BOGZ1FL153067005Q", "BOGZ1FL663067003Q"):
        try:
            rows = fred(sid, "1985-01-01")
            if len(rows) < 60:
                continue
            yoy = [(rows[i][0], (rows[i][1] / rows[i - 4][1] - 1) * 100) for i in range(4, len(rows)) if rows[i - 4][1]]
            d, v = yoy[-1]
            hist = [x[1] for x in yoy[-41:-1]]
            return {"series": sid, "quarter": d, "level_bn": round(rows[-1][1] / 1000, 1), "yoy": round(v, 1), "pctile": _pctile(hist, v),
                    "spark": [round(x[1], 1) for x in yoy[-40:]]}
        except Exception:  # noqa
            continue
    raise ValueError("FRED 마진 시계열 없음")


def youtube(key, cache):
    out = {"channels": []}
    ids = cache.setdefault("yt_ids", {})
    since = datetime.now(timezone.utc) - timedelta(days=7)
    neg = pos = n = 0
    for name in YT_CHANNELS:
        cid = ids.get(name)
        if not cid:
            j = json.loads(_get("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({"part": "snippet", "type": "channel", "q": name, "maxResults": 1, "key": key})))
            cid = j["items"][0]["snippet"]["channelId"]; ids[name] = cid
        ch = json.loads(_get("https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode({"part": "contentDetails", "id": cid, "key": key})))
        upl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = json.loads(_get("https://www.googleapis.com/youtube/v3/playlistItems?" + urllib.parse.urlencode({"part": "contentDetails", "playlistId": upl, "maxResults": 8, "key": key})))
        cn = cneg = cpos = 0
        for it in pl.get("items", []):
            vid = it["contentDetails"]["videoId"]
            tok = None
            for _ in range(3):   # 영상당 최대 300개 최신 댓글
                q = {"part": "snippet", "videoId": vid, "maxResults": 100, "order": "time", "textFormat": "plainText", "key": key}
                if tok:
                    q["pageToken"] = tok
                try:
                    cj = json.loads(_get("https://www.googleapis.com/youtube/v3/commentThreads?" + urllib.parse.urlencode(q)))
                except Exception:  # 댓글 꺼진 영상
                    break
                stop = False
                for c in cj.get("items", []):
                    s = c["snippet"]["topLevelComment"]["snippet"]
                    if datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00")) < since:
                        stop = True; break
                    t = s.get("textDisplay", "")
                    cn += 1
                    cneg += any(k in t for k in YT_NEG); cpos += any(k in t for k in YT_POS)
                tok = cj.get("nextPageToken")
                if stop or not tok:
                    break
        out["channels"].append({"name": name, "comments_7d": cn, "neg": cneg, "pos": cpos})
        n += cn; neg += cneg; pos += cpos
    out.update({"comments_7d": n, "neg": neg, "pos": pos, "neg_ratio": round(neg / (neg + pos) * 100, 1) if neg + pos else None})
    return out


def naver_news(cid, sec):
    since = datetime.now(timezone.utc) - timedelta(days=7)
    def count(q):
        n = 0
        for start in range(1, 1000, 100):
            j = json.loads(_get("https://openapi.naver.com/v1/search/news.json?" + urllib.parse.urlencode({"query": q, "display": 100, "start": start, "sort": "date"}),
                                {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec}))
            items = j.get("items", [])
            if not items:
                break
            older = False
            for it in items:
                if parsedate_to_datetime(it["pubDate"]) >= since:
                    n += 1
                else:
                    older = True
            if older:
                break
            time.sleep(0.15)
        return n
    fear = {q: count(q) for q in NEWS_FEAR}
    greed = {q: count(q) for q in NEWS_GREED}
    f, g = sum(fear.values()), sum(greed.values())
    return {"fear": fear, "greed": greed, "fear_total": f, "greed_total": g, "fear_ratio": round(f / (f + g) * 100, 1) if f + g else None}


def kofia(key):
    base = "https://apis.data.go.kr/1160100/service/GetKofiaStatisticsInfoService"
    end = datetime.now().strftime("%Y%m%d"); beg = (datetime.now() - timedelta(days=800)).strftime("%Y%m%d")
    def fetch(op):
        q = urllib.parse.urlencode({"serviceKey": key, "resultType": "json", "numOfRows": 1000, "pageNo": 1, "beginBasDt": beg, "endBasDt": end})
        j = json.loads(_get(f"{base}/{op}?{q}"))
        items = j["response"]["body"]["items"]["item"]
        return sorted(items, key=lambda x: x.get("basDt", ""))
    cr = fetch("getGrantingOfCreditBalanceInfo")
    fund = fetch("getSecuritiesMarketTotalCapitalInfo")
    def pick(it, pat):
        for k, v in it.items():
            if re.search(pat, k, re.I):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None
    # 필드명: 신용거래융자 합계(crdTrFingWhl 등)·투자자예탁금(invrDpsgAmt 등) — 이름이 바뀌어도 잡도록 패턴 매칭
    cs = [(it["basDt"], pick(it, r"crdTrFing(Whl|Tot|Sum)|crdTrFingAmt")) for it in cr]
    ds = [(it["basDt"], pick(it, r"invrDpsg|InvrDep")) for it in fund]
    cs = [x for x in cs if x[1]]; ds = [x for x in ds if x[1]]
    res = {"fields_credit": list(cr[-1].keys()) if cr else [], "fields_fund": list(fund[-1].keys()) if fund else []}
    if cs:
        v = cs[-1][1]; res["credit"] = {"date": cs[-1][0], "value": v, "pctile_2y": _pctile([x[1] for x in cs[:-1]], v),
                                        "chg_20d": round((v / cs[-21][1] - 1) * 100, 1) if len(cs) > 21 else None, "spark": [x[1] for x in cs[-250:]]}
    if ds:
        v = ds[-1][1]; res["deposit"] = {"date": ds[-1][0], "value": v, "pctile_2y": _pctile([x[1] for x in ds[:-1]], v),
                                         "chg_20d": round((v / ds[-21][1] - 1) * 100, 1) if len(ds) > 21 else None}
    if cs and ds:
        res["credit_to_deposit"] = round(cs[-1][1] / ds[-1][1] * 100, 1)
    return res


def collect(data_dir, fred, now):
    """하루 1회 갱신. 이전 값 유지."""
    prev = {}
    try:
        with open(os.path.join(data_dir, "market.json"), encoding="utf-8") as f:
            prev = json.load(f).get("sentiment") or {}
    except Exception:  # noqa
        pass
    last = prev.get("updated")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < 20 * 3600 and not os.environ.get("FORCE_SENT"):
        return prev
    hp = os.path.join(data_dir, "sentiment_hist.json")
    try:
        with open(hp, encoding="utf-8") as f:
            H = json.load(f)
    except Exception:  # noqa
        H = {"weeks": {}, "cache": {}}
    out = {"updated": now.isoformat(), "errors": []}
    def run(k, fn):
        try:
            out[k] = fn()
        except Exception as e:  # noqa
            out["errors"].append(f"{k}: {type(e).__name__}: {e}"[:200])
            if k in prev:
                out[k] = prev[k]
    run("aaii", aaii)
    run("margin", lambda: fed_margin(fred))
    yk = os.environ.get("YOUTUBE_API_KEY")
    if yk:
        run("youtube", lambda: youtube(yk, H["cache"]))
    nid, nsec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if nid and nsec:
        run("news", lambda: naver_news(nid, nsec))
    dk = os.environ.get("DATA_GO_KR_KEY")
    if dk:
        run("kofia", lambda: kofia(dk))
    # 주간 기록(같은 주는 덮어씀) → 자기 과거 대비 백분위
    y, w, _ = now.isocalendar(); wk = f"{y}-W{w:02d}"
    rec = {}
    if out.get("youtube", {}).get("neg_ratio") is not None:
        rec["yt_neg_ratio"] = out["youtube"]["neg_ratio"]; rec["yt_comments"] = out["youtube"]["comments_7d"]
    if out.get("news", {}).get("fear_ratio") is not None:
        rec["news_fear_ratio"] = out["news"]["fear_ratio"]; rec["news_fear"] = out["news"]["fear_total"]; rec["news_greed"] = out["news"]["greed_total"]
    if rec:
        H["weeks"][wk] = rec
    past = [H["weeks"][k] for k in sorted(H["weeks"]) if k != wk]
    for k in ("yt_neg_ratio", "yt_comments", "news_fear_ratio"):
        if k in rec:
            out.setdefault("weekly_pctile", {})[k] = _pctile([p.get(k) for p in past[-52:]], rec[k])
    out["weeks_recorded"] = len(H["weeks"])
    with open(hp, "w", encoding="utf-8") as f:
        json.dump(H, f, ensure_ascii=False, indent=0)
    return out
