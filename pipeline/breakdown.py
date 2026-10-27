"""지표를 구성 요소로 나눠 보여 주는 데이터를 만듭니다 (무료 소스, 키 불필요).

    python pipeline/breakdown.py site/data

1) 시장 지도 (breakdown/markets.json)
   S&P 500·나스닥 100·코스피·코스닥의 시가총액 상위 종목(pipeline/constituents.json)의
   등락률과 시가총액(Yahoo). 비중은 목록 종목들의 시가총액 합계 기준 근사치입니다.
2) 분해 차트 (breakdown/<지표 id>.json, FRED)
   - ust10y: 기대 단기금리 경로 + 기간 프리미엄 (Fed 이사회 Kim-Wright 모형, THREEFY10·THREEFYTP10)
             실질금리(10년 TIPS, DFII10) + 기대인플레이션(10년 BEI, T10YIE)
   - cpi:    식품·에너지·근원상품·주거비·주거 외 서비스의 전년비 기여도
             (BLS 가중치로 근사, 합계는 실제 CPI 상승률과 조금 다를 수 있음)
   - gdp:    소비·투자·정부·순수출의 성장 기여도 (BEA)
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

HERE = Path(__file__).resolve().parent
CONSTITUENTS = HERE / "constituents.json"
PERIODS = {"w1": pd.DateOffset(weeks=1), "m1": pd.DateOffset(months=1), "y1": pd.DateOffset(years=1)}

# CPI 상대 중요도 (BLS, 2024년 12월 기준, %). 주거 외 서비스 = 에너지 제외 서비스 − 주거비
CPI_WEIGHTS = {"food": 13.6, "energy": 6.4, "goods": 19.0, "shelter": 35.5, "services": 61.0}

STACKS = {
    "ust10y": {
        "title": "미 국채 10년물 금리 분해",
        "charts": [
            {"title": "기대 단기금리 경로 + 기간 프리미엄", "kind": "lines", "unit": "%",
             "note": "Fed 이사회 Kim-Wright 모형. 기간 프리미엄은 장기채를 들고 있는 대가로 더 받는 금리입니다.",
             "total": ("THREEFY10", "10년 금리(모형)"),
             "parts": [("expected", "기대 단기금리 경로"), ("THREEFYTP10", "기간 프리미엄")]},
            {"title": "실질금리 + 기대인플레이션", "kind": "lines", "unit": "%",
             "note": "10년 TIPS 금리와 10년 손익분기 인플레이션(BEI)의 합이 명목 10년 금리와 거의 같습니다.",
             "total": ("DGS10", "명목 10년 금리"),
             "parts": [("DFII10", "실질금리(TIPS)"), ("T10YIE", "기대인플레이션(BEI)")]},
        ],
    },
    "cpi": {
        "title": "미국 CPI 상승률 기여도",
        "charts": [
            {"title": "전년 대비 상승률 기여도", "kind": "stack", "unit": "%p",
             "note": "각 항목 상승률 × BLS 가중치로 근사한 값입니다. 막대 합계와 실제 CPI 상승률(선)은 조금 다를 수 있습니다.",
             "total": ("CPIAUCSL", "CPI 상승률"),
             "parts": [("food", "식품"), ("energy", "에너지"), ("goods", "근원 상품"),
                       ("shelter", "주거비"), ("svc_ex", "주거 외 서비스")]},
        ],
    },
    "gdp": {
        "title": "미국 GDP 성장 기여도",
        "charts": [
            {"title": "성장률(연율) 기여도", "kind": "stack", "unit": "%p",
             "note": "미 상무부(BEA) 발표 기여도. 막대 합계가 실질 GDP 성장률(선)입니다.",
             "total": ("A191RL1Q225SBEA", "실질 GDP 성장률"),
             "parts": [("DPCERY2Q224SBEA", "소비"), ("A006RY2Q224SBEA", "투자"),
                       ("A822RY2Q224SBEA", "정부"), ("A019RY2Q224SBEA", "순수출")]},
        ],
    },
}
CPI_CODES = {"food": "CPIUFDSL", "energy": "CPIENGSL", "goods": "CUSR0000SACL1E",
             "shelter": "CUSR0000SAH1", "services": "CUSR0000SASLE"}
START = {"ust10y": "2016-01-01", "cpi": "2019-01-01", "gdp": "2015-01-01"}


# ── 시장 지도 ───────────────────────────────────────────
def fetch_prices(tickers):
    import yfinance as yf
    start = (pd.Timestamp.now() - pd.DateOffset(years=1, days=10)).strftime("%Y-%m-%d")
    df = yf.download(tickers, start=start, interval="1d", auto_adjust=False, progress=False, threads=True)
    close = df["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    out = {}
    for t in tickers:
        if t in close.columns:
            s = close[t].dropna()
            if len(s) >= 2:
                s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                out[t] = s.astype(float)
    return out


def _cap(t):
    import yfinance as yf
    try:
        v = yf.Ticker(t).fast_info["marketCap"]
        return float(v) if v and v > 0 else None
    except Exception:  # noqa: BLE001
        return None


def fetch_caps(tickers):
    with ThreadPoolExecutor(8) as ex:
        return {t: c for t, c in zip(tickers, ex.map(_cap, tickers)) if c}


def changes(s):
    last_d, last = s.index[-1], s.iloc[-1]

    def pct(ref):
        return round((last / ref - 1) * 100, 2) if ref and ref > 0 else None

    out = {"prev": pct(s.iloc[-2])}
    for k, off in PERIODS.items():
        before = s[s.index <= last_d - off]
        out[k] = pct(before.iloc[-1]) if len(before) else None
    ytd = s[s.index < pd.Timestamp(year=last_d.year, month=1, day=1)]
    out["ytd"] = pct(ytd.iloc[-1]) if len(ytd) else None
    return out


def build_markets(config, fetch_prices=fetch_prices, fetch_caps=fetch_caps, log=print):
    tickers = sorted({i["t"] for m in config["markets"] for i in m["items"]})
    prices = fetch_prices(tickers)
    caps = fetch_caps(sorted(prices))
    markets = []
    for m in config["markets"]:
        items = []
        for i in m["items"]:
            s, cap = prices.get(i["t"]), caps.get(i["t"])
            if s is None or cap is None:
                continue
            items.append({"t": i["t"].split(".")[0], "n": i["n"], "s": i["s"], "cap": round(cap),
                          "price": round(float(s.iloc[-1]), 2), "date": s.index[-1].strftime("%Y-%m-%d"),
                          "chg": changes(s)})
        total = sum(x["cap"] for x in items) or 1
        for x in items:
            x["w"] = round(x["cap"] / total * 100, 3)
        items.sort(key=lambda x: -x["cap"])
        log(f"시장 지도 {m['name']}: {len(items)}/{len(m['items'])}개 종목")
        if items:
            markets.append({"id": m["id"], "name": m["name"], "as_of": max(x["date"] for x in items), "items": items})
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "markets": markets}


# ── 분해 차트 ───────────────────────────────────────────
def _yoy(s):
    return (s / s.shift(12) - 1) * 100


def component_frames(fetch_fred, log=print):
    """분해 차트별로 필요한 시계열을 받아 하나의 DataFrame으로."""
    raw = {}

    def get(code):
        if code not in raw:
            try:
                raw[code] = fetch_fred(code)
            except Exception as e:  # noqa: BLE001
                log(f"  분해 데이터 실패 {code}: {str(e)[:100]}")
                raw[code] = None
        return raw[code]

    frames = {}
    # 10년물
    cols = {c: get(c) for c in ("THREEFY10", "THREEFYTP10", "DGS10", "DFII10", "T10YIE")}
    if all(v is not None for v in cols.values()):
        df = pd.DataFrame(cols).ffill().dropna()
        df["expected"] = df["THREEFY10"] - df["THREEFYTP10"]
        frames["ust10y"] = df
    # CPI
    cols = {k: get(c) for k, c in {**CPI_CODES, "CPIAUCSL": "CPIAUCSL"}.items()}
    if all(v is not None for v in cols.values()):
        y = pd.DataFrame({k: _yoy(v) for k, v in cols.items()}).dropna()
        w = CPI_WEIGHTS
        df = pd.DataFrame({
            "food": y["food"] * w["food"] / 100,
            "energy": y["energy"] * w["energy"] / 100,
            "goods": y["goods"] * w["goods"] / 100,
            "shelter": y["shelter"] * w["shelter"] / 100,
            "svc_ex": (y["services"] * w["services"] - y["shelter"] * w["shelter"]) / 100,
            "CPIAUCSL": y["CPIAUCSL"],
        })
        frames["cpi"] = df
    # GDP
    codes = ["A191RL1Q225SBEA", "DPCERY2Q224SBEA", "A006RY2Q224SBEA", "A822RY2Q224SBEA", "A019RY2Q224SBEA"]
    cols = {c: get(c) for c in codes}
    if all(v is not None for v in cols.values()):
        frames["gdp"] = pd.DataFrame(cols).dropna()
    return frames


def _weekly(df):
    """일별 자료는 화면 부담을 줄이려 주간(금요일)으로."""
    return df.resample("W-FRI").last().dropna(how="all")


def build_stacks(frames):
    out = {}
    for ind_id, spec in STACKS.items():
        df = frames.get(ind_id)
        if df is None or df.empty:
            continue
        df = df[df.index >= START[ind_id]]
        if ind_id == "ust10y":
            df = _weekly(df)
        charts = []
        for c in spec["charts"]:
            tcode, tname = c["total"]
            cols = [tcode] + [p for p, _ in c["parts"]]
            d = df[cols].dropna()
            if d.empty:
                continue
            charts.append({
                "title": c["title"], "kind": c["kind"], "unit": c["unit"], "note": c["note"],
                "dates": [x.strftime("%Y-%m-%d") for x in d.index],
                "total": {"name": tname, "values": [round(float(v), 3) for v in d[tcode]]},
                "parts": [{"name": n, "values": [round(float(v), 3) for v in d[p]]} for p, n in c["parts"]],
            })
        if charts:
            out[ind_id] = {"id": ind_id, "title": spec["title"], "charts": charts}
    return out


def write(data_dir, fetch_fred=collect.fetch_fred, fetch_prices=fetch_prices, fetch_caps=fetch_caps, log=print):
    out = Path(data_dir) / "breakdown"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        config = json.loads(CONSTITUENTS.read_text(encoding="utf-8"))
        markets = build_markets(config, fetch_prices, fetch_caps, log)
        if markets["markets"]:
            (out / "markets.json").write_text(json.dumps(markets, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            written.append("markets")
    except Exception as e:  # noqa: BLE001
        log(f"시장 지도 실패: {str(e)[:200]}")
    stacks = build_stacks(component_frames(fetch_fred, log))
    for ind_id, d in stacks.items():
        (out / f"{ind_id}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        written.append(ind_id)
    (out / "index.json").write_text(json.dumps(sorted(stacks)), encoding="utf-8")
    log(f"분해 데이터: {', '.join(written) or '없음'}")
    return written


def main(argv):
    write(argv[1] if len(argv) > 1 else "site/data")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
