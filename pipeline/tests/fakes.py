"""테스트·화면 확인용 가짜 수집기."""
import numpy as np
import pandas as pd


def daily(start="2009-01-01", end="2026-10-23", base=100.0, seed=0):
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    return pd.Series(base * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx)


def monthly(start="1999-01-01", end="2026-09-01", base=100.0):
    idx = pd.date_range(start, end, freq="MS")
    return pd.Series(base * 1.002 ** np.arange(len(idx)), index=idx)


def fake_fred(code, key=None, session=None):
    if code in ("CPIAUCSL", "CPILFESL", "PCEPILFE", "PAYEMS"):
        return monthly()
    if code in ("UNRATE",):
        return monthly() / 25
    if code == "A191RL1Q225SBEA":
        return pd.Series([2.0, 3.1, 1.4], index=pd.to_datetime(["2025-10-01", "2026-01-01", "2026-04-01"]))
    if code == "GDPNOW":
        return pd.Series([3.0, 1.6, 2.4], index=pd.to_datetime(["2026-01-01", "2026-04-01", "2026-07-01"]))
    if code.endswith("MD"):  # FOMC 연도별 전망
        return pd.Series([3.9, 3.6, 3.4, 3.1], index=pd.to_datetime(["2025-01-01", "2026-01-01", "2027-01-01", "2028-01-01"]))
    return daily(base=4.0, seed=len(code)) / 25 + 3


def fake_yahoo(codes):
    return {c: daily(seed=i) for i, c in enumerate(codes)}


def fake_lme(code, session=None):
    return daily(base=10000.0, seed=len(code) + 7)


def fake_news(query, date, session=None):
    return [{"title": f"{query} 관련 뉴스 {date:%m/%d} #{k}", "url": f"https://example.com/{k}",
             "source": "테스트일보", "published": date.strftime("%Y-%m-%d")} for k in range(1, 3)]
