"""임시 진단: 대체 데이터 출처 접근 가능 여부 (머지 전에 삭제)."""
import os
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
print("FRED_API_KEY set:", bool(os.environ.get("FRED_API_KEY")))


def probe(name, url, pat=None, headers=UA, n=400):
    try:
        r = requests.get(url, headers=headers, timeout=25)
        t = r.text
        print(f"== {name}: {r.status_code} len={len(t)}")
        if pat:
            for m in list(re.finditer(pat, t, re.I | re.S))[:6]:
                print("   ", re.sub(r"\s+", " ", t[max(0, m.start() - 80): m.end() + 160])[:300])
        else:
            print("   ", re.sub(r"\s+", " ", t[:n]))
    except Exception as e:  # noqa: BLE001
        print(f"== {name}: ERR {str(e)[:200]}")


probe("westmetall", "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash", r"\d{1,2}\. \w+ 2026")
probe("westmetall-plainUA", "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash", r"\d{1,2}\. \w+ 2026",
      headers={"User-Agent": "Mozilla/5.0 (global-economy-dashboard; +https://github.com/navy588/dash)"})
probe("investing-page", "https://www.investing.com/commodities/copper-historical-data", r"historical|\d{2}/\d{2}/2026")
probe("investing-api", "https://api.investing.com/api/financialdata/historical/8831?start-date=2026-10-01&end-date=2026-10-28&time-frame=Daily&add-missing-rows=false",
      headers={**UA, "domain-id": "www"})
probe("kr-investing", "https://kr.investing.com/commodities/copper-historical-data", r"\d{4}- ?\d{2}- ?\d{2}|historical")
probe("fred-series-page", "https://fred.stlouisfed.org/series/CPIAUCSL", r"next release|release date|Updated:")
probe("fred-release-cal", "https://fred.stlouisfed.org/releases/calendar?rid=10&y=2026", r"Nov(ember)?\.? \d{1,2}|2026-11")
probe("fred-release-dates", "https://fred.stlouisfed.org/release?rid=10", r"next release|release date")
probe("bls-cpi-schedule", "https://www.bls.gov/schedule/news_release/cpi.htm", r"Nov\. \d{1,2}, 2026|November \d{1,2}, 2026")
probe("bea-schedule", "https://www.bea.gov/news/schedule", r"GDP")
probe("ecos-sample", "https://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/200Y102/Q/2025Q1/2026Q4/10111")
probe("ecos-sample-list", "https://ecos.bok.or.kr/api/StatisticTableList/sample/json/kr/1/5/200Y102")
probe("oecd-qna-kor", "https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,/Q..KOR.S1..B1GQ......G1.?startPeriod=2025-Q1&format=csvfilewithlabels",
      n=1500)
probe("oecd-qna-all", "https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA,1.1/all?startPeriod=2026-Q2&c[REF_AREA]=KOR&format=csvfilewithlabels", n=800)
probe("kostat-calendar", "https://kostat.go.kr/board.es?mid=a10301010000&bid=11738", r"2026")
probe("unipass", "https://unipass.customs.go.kr/ets/", None, n=200)
