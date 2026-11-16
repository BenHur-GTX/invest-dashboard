import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
from build_data import fred, http_get
for sid in ["MYAGM2KRM189S","MABMM301KRM189S","MABMM301KRM657S","MANMM101KRM189S","KORM2","MABMM201KRM189S"]:
    try:
        r=fred(sid,"2015-01-01"); print("FRED",sid,len(r),r[:1],r[-2:])
    except Exception as e: print("FRED",sid,"ERR",str(e)[:120])
for key in [os.environ.get("ECOS_KEY") or "sample","sample"]:
    for url in [f"https://ecos.bok.or.kr/api/StatisticTableList/{key}/json/kr/1/10/101Y003",
                f"https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/10/101Y003",
                f"https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/10/101Y004",
                f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10/101Y003/M/202401/202610/BBHS00",
                f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10/101Y004/M/202401/202610/BBHA00",
                f"https://ecos.bok.or.kr/api/StatisticTableList/{key}/json/kr/1/100"]:
        try: print("ECOS",url.split('/api/')[1][:80], http_get(url)[:900])
        except Exception as e: print("ECOS ERR",url[:90],str(e)[:120])
    break
