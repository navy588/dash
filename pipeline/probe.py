"""임시 진단: 대체 데이터 출처 접근 가능 여부 (머지 전에 삭제)."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}


def probe(name, url, pat=None, headers=UA, n=600, win=(80, 300)):
    try:
        r = requests.get(url, headers=headers, timeout=20)
        t = r.text
        print(f"== {name}: {r.status_code} len={len(t)}")
        if pat:
            for m in list(re.finditer(pat, t, re.I | re.S))[:8]:
                print("   ", re.sub(r"\s+", " ", t[max(0, m.start() - win[0]): m.end() + win[1]]))
        else:
            print("   ", re.sub(r"\s+", " ", t[:n]))
    except Exception as e:  # noqa: BLE001
        print(f"== {name}: ERR {repr(e)[-300:]}")


E = "https://ecos.bok.or.kr/api"
probe("ecos-gdp", f"{E}/StatisticSearch/sample/json/kr/1/10/200Y102/Q/2025Q1/2026Q4/10111", r'"TIME":"[^"]+","DATA_VALUE":"[^"]+"', win=(0, 0))
probe("ecos-cpi", f"{E}/StatisticSearch/sample/json/kr/1/10/901Y009/M/202601/202612/0", r'"ITEM_NAME1":"[^"]+"|"TIME":"[^"]+","DATA_VALUE":"[^"]+"', win=(0, 0))
for code in ("901Y027", "901Y011", "901Y118", "403Y003", "901Y014"):
    probe(f"ecos-items-{code}", f"{E}/StatisticItemList/sample/json/kr/1/10/{code}", r'"STAT_NAME":"[^"]+"|"ITEM_CODE":"[^"]+","ITEM_NAME":"[^"]+"', win=(0, 0))
probe("ecos-key", f"{E}/KeyStatisticList/sample/json/kr/1/10", n=1500)
probe("bea-row", "https://www.bea.gov/news/schedule", r"<tr[^>]*>\s*<td[^>]*scheduled-date.{0,900}?</tr>", win=(0, 0))
probe("westmetall-http", "http://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash", r"\d{1,2}\. \w+ 2026")
probe("westmetall-root", "https://westmetall.com/")
probe("kitco-base", "https://www.kitco.com/price/base-metals", r"copper|nickel", win=(60, 120))
probe("bi-copper", "https://markets.businessinsider.com/commodities/copper-price", r"price-section__current-value[^>]*>[^<]+", win=(0, 20))
probe("bi-nickel", "https://markets.businessinsider.com/commodities/nickel-price", r"price-section__current-value[^>]*>[^<]+", win=(0, 20))
probe("lme-api", "https://www.lme.com/api/trading-data/day-delayed?datasourceId=1a0ef0b6-3ee6-4e44-a415-7a313d5bd771", n=300)
probe("stooq-cu", "https://stooq.com/q/l/?s=hg.f&f=sd2t2ohlcv&h&e=csv", n=300)
try:
    import yfinance as yf
    df = yf.download(["HG=F", "ALI=F", "NICKEL=F", "NI=F"], period="10d", progress=False)["Close"]
    print("== yahoo:\n", df.tail(4).to_string())
except Exception as e:  # noqa: BLE001
    print("== yahoo ERR", e)
