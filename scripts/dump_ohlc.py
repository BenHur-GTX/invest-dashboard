"""11-17: 일목균형표 연구용 OHLC 덤프 → data/_ohlc.json (분석 후 삭제)"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import build_data as B
out = {}
for s in ["QQQ", "^NDX", "^IXIC", "BTC-USD", "QLD", "^IRX", "^KS11"]:
    try:
        r = B.yahoo(s, "max"); out[s] = [[d, round(o, 4), round(h, 4), round(l, 4), round(c, 4), round(a, 4)] for d, o, h, l, c, a in r]
        print(s, len(r), r[0][0], r[-1][0], flush=True)
    except Exception as e:
        print("fail", s, e)
json.dump(out, open(os.path.join(B.DATA, "_ohlc.json"), "w"), separators=(",", ":"))
