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
    if code in ("A191RL1Q225SBEA", "GDPNOW"):
        return pd.Series([2.0, 3.1, 1.4], index=pd.to_datetime(["2026-01-01", "2026-04-01", "2026-07-01"]))
    return daily(base=4.0, seed=len(code)) / 25 + 3


def fake_yahoo(codes):
    return {c: daily(seed=i) for i, c in enumerate(codes)}
