"""유튜브 댓글 심리 사전 (실시간 수집 sentiment.py와 과거 검증 yt_backfill.py가 함께 씀).

CANDIDATES: 검증용 후보 단어(단계 가설별). 과거 주간 데이터로 QQQ 낙폭·이후 수익과 맞는지 보고 STAGES를 고름.
STAGES: 실제 판정에 쓰는 단어. 공백을 지운 댓글에 부분 일치.
"""
import re

# 단계 가설: 극공포(항복) / 공포(불안) / 저가매수(역발상 매수 의지) / 탐욕(낙관) / 극탐욕(도취·FOMO)
CANDIDATES = {
    "극공포": ["반대매매", "깡통", "마진콜", "강제청산", "손절", "다팔았", "전량매도", "한강", "탈출", "끝났", "망했", "폭망",
             "살려", "멘탈나", "포기", "그만할", "주식접", "손실", "-50%", "-30%", "반토막"],
    "공포": ["무섭", "무서워", "불안", "공포", "폭락", "대폭락", "하락장", "약세장", "침체", "대공황", "붕괴", "물렸", "멘붕",
           "패닉", "바닥이어디", "지하실", "현금확보", "지옥", "위기", "버블", "거품", "떨어지"],
    "저가매수": ["줍줍", "바겐세일", "세일", "기회", "분할매수", "추매", "추가매수", "물타기", "저점매수", "싸게", "모아가"],
    "탐욕": ["수익", "익절", "떡상", "신고가", "불장", "상승장", "가즈아", "축하", "올랐", "회복", "반등", "+%"],
    "극탐욕": ["풀매수", "몰빵", "영끌", "빚투", "대출", "신용", "레버리지", "tqqq", "3배", "졸업", "퇴사", "인증", "포모",
             "fomo", "벼락거지", "나만못", "인생역전", "경제적자유", "파이어족", "부자", "천만원", "억벌"],
}

# 판정용 사전: yt_backfill 검증 후 확정(2026-11). 검증 전에는 후보 전체를 씀.
STAGES = CANDIDATES
WEIGHT = {"극공포": -2, "공포": -1, "저가매수": 0, "탐욕": 1, "극탐욕": 2}

_ws = re.compile(r"\s+")


def norm(t):
    return _ws.sub("", (t or "").lower())


def hits(text, lex=None):
    """댓글 1개 → 걸린 후보 단어 집합"""
    t = norm(text)
    out = set()
    for st, ws in (lex or CANDIDATES).items():
        for w in ws:
            if w == "+%":
                if re.search(r"\+\d+(\.\d+)?%", t):
                    out.add(w)
            elif w in t:
                out.add(w)
    return out


def stage_of(words, lex=None):
    """댓글에 걸린 단어 → 단계(가장 센 쪽). 공포·탐욕이 둘 다 걸리면 가중합 부호, 0이면 None."""
    lex = lex or STAGES
    s = 0; got = []
    for st, ws in lex.items():
        if any(w in words for w in ws):
            got.append(st); s += WEIGHT[st]
    if not got:
        return None
    if s < 0:
        return "극공포" if "극공포" in got else "공포"
    if s > 0:
        return "극탐욕" if "극탐욕" in got else "탐욕"
    return "저가매수" if got == ["저가매수"] else None


def score(counts):
    """단계별 댓글 수 → 0(극공포)~100(극탐욕). 저가매수는 제외. 걸린 댓글 20개 미만이면 None."""
    f2, f1, g1, g2 = (counts.get(k, 0) for k in ("극공포", "공포", "탐욕", "극탐욕"))
    m = f2 + f1 + g1 + g2
    if m < 20:
        return None
    return round(50 + 50 * (2 * g2 + g1 - f1 - 2 * f2) / (2 * m), 1)
