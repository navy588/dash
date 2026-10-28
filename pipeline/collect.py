"""글로벌 경제 지표를 수집해 정적 대시보드용 JSON을 만듭니다.

    python pipeline/collect.py --out site/data

지표 목록은 pipeline/indicators.json 한 곳에서 관리합니다.
- FRED: FRED_API_KEY가 있으면 공식 API, 없으면 키가 필요 없는 fredgraph CSV를 사용합니다.
- Yahoo Finance: yfinance로 일별 종가를 받습니다.
- LME 금속: westmetall.com의 LME 현금 결제가 표를 읽습니다.
- 각국 기준금리: BIS(국제결제은행) 공개 통계 API, 키 불필요.
- 수집에 실패한 지표는 PREVIOUS_DATA_URL(직전 배포본)의 값을 그대로 쓰고 status를 "stale"로 표시합니다.

출력
    <out>/latest.json          지표별 최신값·변화·추세선, 금리 커브, 수집 상태
    <out>/series/<id>.json     지표별 전체 시계열 {"id", "dates", "values"}
    <out>/indicators.json      지표 정의 사본
"""
import argparse
import io
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

import releases

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE / "indicators.json"

# 시계열 보관 시작일: 일·주 단위는 최근 위주, 월·분기 단위는 장기
START = {"daily": "2010-01-01", "weekly": "2010-01-01", "monthly": "2000-01-01", "quarterly": "2000-01-01"}
FETCH_START = "1999-01-01"  # 전년비 계산을 위해 1년 더 받음
SPARK_POINTS = {"daily": 90, "weekly": 52, "monthly": 36, "quarterly": 20}
HTTP_TIMEOUT = 30


def load_registry(path=REGISTRY_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 수집 ────────────────────────────────────────────────────

def _session():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (global-economy-dashboard; +https://github.com/navy588/dash)"
    adapter = requests.adapters.HTTPAdapter(max_retries=3)
    s.mount("https://", adapter)
    return s


def fetch_fred(code, api_key=None, session=None):
    """FRED 시계열을 pd.Series(float, DatetimeIndex)로 반환."""
    session = session or _session()
    if api_key:
        r = session.get("https://api.stlouisfed.org/fred/series/observations", timeout=HTTP_TIMEOUT, params={
            "series_id": code, "api_key": api_key, "file_type": "json", "observation_start": FETCH_START})
        r.raise_for_status()
        obs = r.json()["observations"]
        s = pd.Series({o["date"]: o["value"] for o in obs})
    else:
        r = session.get("https://fred.stlouisfed.org/graph/fredgraph.csv", timeout=HTTP_TIMEOUT,
                        params={"id": code, "cosd": FETCH_START})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        s = pd.Series(df.iloc[:, 1].values, index=df.iloc[:, 0].values)
    s.index = pd.to_datetime(s.index)
    return pd.to_numeric(s, errors="coerce").dropna().sort_index()


def fetch_yahoo(codes):
    """여러 티커의 일별 종가를 {티커: pd.Series}로 반환. 받지 못한 티커는 빠집니다."""
    import yfinance as yf
    df = yf.download(codes, start=FETCH_START, interval="1d", auto_adjust=False,
                     progress=False, threads=True, group_by="column")
    close = df["Close"] if "Close" in df else df
    if isinstance(close, pd.Series):
        close = close.to_frame(codes[0])
    out = {}
    for code in codes:
        if code in close.columns:
            s = close[code].dropna()
            if len(s):
                s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                out[code] = s.astype(float)
    return out


def fetch_lme(code, session=None):
    """LME 현금 결제가(일별, $/t)를 westmetall.com 표에서 읽습니다. code 예: LME_Cu_cash"""
    session = session or _session()
    err = None
    # www 주소는 GitHub 실행기에서 접속이 막힐 때가 있어 다른 주소로도 시도
    for base in ("https://westmetall.com", "https://www.westmetall.com", "http://www.westmetall.com"):
        try:
            r = session.get(f"{base}/en/markdaten.php", timeout=HTTP_TIMEOUT, params={"action": "table", "field": code})
            r.raise_for_status()
            return parse_lme_html(r.text)
        except Exception as e:  # noqa: BLE001
            err = e
    raise err


def parse_lme_html(html):
    tables = pd.read_html(io.StringIO(html), thousands=",", decimal=".")
    parts = []
    for t in tables:
        if t.shape[1] < 2:
            continue
        dates = pd.to_datetime(t.iloc[:, 0].astype(str).str.strip(), format="%d. %B %Y", errors="coerce")
        values = pd.to_numeric(t.iloc[:, 1].astype(str).str.replace(",", ""), errors="coerce")
        part = pd.Series(values.values, index=dates.values).dropna()
        part = part[part.index.notna()]
        if len(part):
            parts.append(part)
    if not parts:
        raise ValueError("LME 표를 찾지 못했습니다")
    s = pd.concat(parts)
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s[s.index >= FETCH_START].astype(float)


def fetch_bis(code, session=None):
    """BIS 통계. code 예: D.KR (정책금리 WS_CBPOL, 일별 한국), WS_LONG_CPI/M.KR.771 (데이터셋/키)"""
    session = session or _session()
    dataset, key = code.split("/", 1) if "/" in code else ("WS_CBPOL", code)
    r = session.get(f"https://stats.bis.org/api/v1/data/{dataset}/{key}", timeout=HTTP_TIMEOUT,
                    params={"format": "csv", "startPeriod": FETCH_START})
    r.raise_for_status()
    return parse_bis_csv(r.text)


ECOS_ROWS = 10  # 공개 시험용 키(sample)는 한 번에 10개까지만 줍니다


def ecos_periods(cycle, n, today=None):
    """오늘까지 최근 n개 기간 코드 (Q: 2026Q3, M: 202609)."""
    p = pd.Period(today or pd.Timestamp.now(), freq="Q" if cycle == "Q" else "M")
    out = [p - k for k in range(n)][::-1]
    return [f"{x.year}Q{x.quarter}" if cycle == "Q" else f"{x.year}{x.month:02d}" for x in out]


def fetch_ecos(code, key=None, session=None, periods=20, today=None):
    """한국은행 ECOS 통계 최근 값. code 예: 200Y102/Q/10111 (통계표/주기/항목).

    ECOS_API_KEY가 없으면 공개 시험용 키로 10개씩 나눠 받습니다.
    """
    session = session or _session()
    key = key or os.environ.get("ECOS_API_KEY", "").strip() or "sample"
    stat, cycle, item = code.split("/")
    want = ecos_periods(cycle, periods, today)
    chunks = [want[i:i + ECOS_ROWS] for i in range(0, len(want), ECOS_ROWS)] if key == "sample" else [want]
    rows = []
    for c in chunks:
        r = session.get(f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/{max(len(c), ECOS_ROWS)}"
                        f"/{stat}/{cycle}/{c[0]}/{c[-1]}/{item}", timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        d = r.json()
        if "StatisticSearch" not in d:
            if c is chunks[-1] and not rows:
                raise ValueError(f"ECOS 응답 오류: {str(d)[:150]}")
            continue
        rows += d["StatisticSearch"]["row"]
    return parse_ecos_rows(rows)


def parse_ecos_rows(rows):
    def when(t):
        return pd.Period(t.replace("Q", "-Q"), freq="Q").start_time if "Q" in t else pd.Timestamp(f"{t[:4]}-{t[4:6]}-01")
    s = pd.Series({when(r["TIME"]): r["DATA_VALUE"] for r in rows})
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
    if not len(s):
        raise ValueError("ECOS 데이터가 비어 있습니다")
    return s.astype(float)


def parse_bis_csv(text):
    df = pd.read_csv(io.StringIO(text))
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values,
                  index=pd.to_datetime(df["TIME_PERIOD"], errors="coerce"))
    s = s[s.index.notna()].dropna().sort_index()
    if not len(s):
        raise ValueError("BIS 데이터가 비어 있습니다")
    return s.astype(float)


def forecast_points(raw, ind, last_date):
    """전망 시계열을 실제치 마지막 날짜 이후의 점들로 바꿉니다.

    FOMC 전망(…MD)은 연도별 값이라 그 해 12월(일별 지표는 12월 31일)에 놓고,
    GDPNow처럼 분기별 값은 날짜 그대로 씁니다.
    """
    pts = []
    for d, v in raw.items():
        if ind["forecast"]["code"].endswith("MD"):
            d = pd.Timestamp(year=d.year, month=12, day=31 if ind["freq"] == "daily" else 1)
        if d > last_date:
            pts.append({"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)})
    return pts


def fetch_previous(base_url, ind_id, session=None):
    """직전 배포본의 시계열을 pd.Series로. 없으면 None."""
    if not base_url:
        return None
    session = session or _session()
    try:
        r = session.get(f"{base_url.rstrip('/')}/series/{ind_id}.json", timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        return pd.Series(d["values"], index=pd.to_datetime(d["dates"]), dtype=float)
    except Exception:  # noqa: BLE001
        return None


# ── 가공 ────────────────────────────────────────────────────

def transform(raw, ind, fx=None):
    s = raw.astype(float)
    if ind.get("fx"):  # 통화 환산 (예: €/MWh × 유로/달러 → $/MWh)
        if fx is None:
            raise ValueError(f"환율 {ind['fx']} 없음")
        rate = fx.reindex(s.index.union(fx.index)).ffill().reindex(s.index)
        s = (s * rate).dropna()
    t = ind.get("transform")
    if t == "yoy":
        s = (s / s.shift(12) - 1) * 100 if ind["freq"] == "monthly" else (s / s.shift(4) - 1) * 100
    elif t == "diff":
        s = s.diff()
    if ind.get("scale"):
        s = s * ind["scale"]
    s = s.dropna()
    return s[s.index >= START[ind["freq"]]]


def change(value, ref, kind):
    if ref is None or value is None or (isinstance(ref, float) and math.isnan(ref)):
        return None
    if kind == "pct":
        return None if ref == 0 else (value / ref - 1) * 100
    if kind == "bp":
        return (value - ref) * 100
    return value - ref  # pp, abs


def value_at(s, when):
    """when 시점 이전(포함) 마지막 관측치."""
    sub = s[s.index <= when]
    return (sub.index[-1], float(sub.iloc[-1])) if len(sub) else (None, None)


def summarize(s, ind):
    last_date, last = s.index[-1], float(s.iloc[-1])
    refs = {
        "prev": (s.index[-2], float(s.iloc[-2])) if len(s) > 1 else (None, None),
        "w1": value_at(s, last_date - pd.DateOffset(weeks=1)),
        "m1": value_at(s, last_date - pd.DateOffset(months=1)),
        "ytd": value_at(s, pd.Timestamp(year=last_date.year - 1, month=12, day=31)),
        "y1": value_at(s, last_date - pd.DateOffset(years=1)),
    }
    changes = {}
    for k, (d, v) in refs.items():
        c = change(last, v, ind["change"])
        changes[k] = None if c is None else {"value": round(c, 4), "ref_date": d.strftime("%Y-%m-%d"), "ref": v}

    # 직전 대비 변화가 최근 1년 변화 분포에서 몇 표준편차인지 (급변 강조용)
    sigma = None
    year = s[s.index > last_date - pd.DateOffset(years=1)]
    diffs = pd.Series([change(b, a, ind["change"]) for a, b in zip(year.iloc[:-1], year.iloc[1:])], dtype=float)
    diffs = diffs.dropna()
    if len(diffs) >= 10 and changes["prev"] and diffs.std() > 0:
        sigma = round(changes["prev"]["value"] / diffs.std(), 2)

    spark = s.iloc[-SPARK_POINTS[ind["freq"]]:]
    return {
        "last": {"date": last_date.strftime("%Y-%m-%d"), "value": last},
        "changes": changes,
        "sigma": sigma,
        "spark": [round(float(v), 6) for v in spark.values],
    }


def series_json(ind_id, s, decimals):
    nd = decimals + 2
    return {"id": ind_id, "dates": [d.strftime("%Y-%m-%d") for d in s.index],
            "values": [round(float(v), nd) for v in s.values]}


def build_curve(curve_def, fred_raw):
    points = []
    for p in curve_def:
        s = fred_raw.get(p["code"])
        if s is None or not len(s):
            continue
        last_date = s.index[-1]
        points.append({
            "label": p["label"], "months": p["months"], "code": p["code"],
            "now": float(s.iloc[-1]), "now_date": last_date.strftime("%Y-%m-%d"),
            "m1": value_at(s, last_date - pd.DateOffset(months=1))[1],
            "y1": value_at(s, last_date - pd.DateOffset(years=1))[1],
        })
    return points


# ── 전체 실행 ───────────────────────────────────────────────

def collect(registry, fred_key=None, previous_url=None,
            fetch_fred=fetch_fred, fetch_yahoo=fetch_yahoo, fetch_previous=fetch_previous,
            fetch_lme=fetch_lme, fetch_bis=fetch_bis, fetch_ecos=fetch_ecos, log=print):
    inds = registry["indicators"]
    errors = {}

    # FRED (지표 + 금리 커브)
    fred_codes = list(dict.fromkeys([i["code"] for i in inds if i["source"] == "fred"] +
                                    [i["forecast"]["code"] for i in inds if i.get("forecast")] +
                                    [p["code"] for p in registry.get("curve", [])]))
    fred_raw = {}
    session = _session()
    for code in fred_codes:
        try:
            fred_raw[code] = fetch_fred(code, fred_key, session)
        except Exception as e:  # noqa: BLE001
            errors[code] = str(e)[:200]
    log(f"FRED: {len(fred_raw)}/{len(fred_codes)}개 수집 ({'API' if fred_key else 'CSV'})")

    # Yahoo
    yahoo_codes = [i["code"] for i in inds if i["source"] == "yahoo"]
    try:
        yahoo_raw = fetch_yahoo(yahoo_codes)
    except Exception as e:  # noqa: BLE001
        yahoo_raw = {}
        errors["yahoo"] = str(e)[:200]
    for code in yahoo_codes:
        if code not in yahoo_raw:
            errors.setdefault(code, "데이터 없음")
    log(f"Yahoo: {len(yahoo_raw)}/{len(yahoo_codes)}개 수집")

    # LME (westmetall)
    lme_codes = [i["code"] for i in inds if i["source"] == "lme"]
    lme_raw = {}
    for code in lme_codes:
        try:
            lme_raw[code] = fetch_lme(code)
        except Exception as e:  # noqa: BLE001
            errors[code] = str(e)[:200]
    if lme_codes:
        log(f"LME: {len(lme_raw)}/{len(lme_codes)}개 수집")

    # BIS 정책금리
    bis_codes = [i["code"] for i in inds if i["source"] == "bis"]
    bis_raw = {}
    for code in bis_codes:
        try:
            bis_raw[code] = fetch_bis(code)
        except Exception as e:  # noqa: BLE001
            errors[code] = str(e)[:200]
    if bis_codes:
        log(f"BIS: {len(bis_raw)}/{len(bis_codes)}개 수집")

    # 최근 값 보강 (예: 한국 지표는 ECOS가 FRED·BIS보다 몇 달 빠름)
    recent = {}
    for ind in inds:
        rc = ind.get("recent")
        if not rc:
            continue
        try:
            r = fetch_ecos(rc["code"], periods=rc.get("periods", 20))
            recent[ind["id"]] = transform(r, {**ind, "transform": rc.get("transform")})
        except Exception as e:  # noqa: BLE001
            errors[rc["code"]] = str(e)[:200]
    if recent:
        log(f"ECOS 최근 값: {len(recent)}/{sum(1 for i in inds if i.get('recent'))}개")

    raw = {**fred_raw, **yahoo_raw, **lme_raw, **bis_raw}
    series, items = {}, []
    for ind in inds:
        status, s = "ok", None
        if ind["code"] in raw:
            try:
                s = transform(raw[ind["code"]], ind, raw.get(ind.get("fx")))
            except Exception as e:  # noqa: BLE001
                errors[ind["code"]] = f"가공 실패: {e}"
        if s is None or len(s) < 2:
            s = fetch_previous(previous_url, ind["id"])
            status = "stale" if s is not None and len(s) >= 2 else "missing"
        if ind["id"] in recent:
            r = recent[ind["id"]]
            s = r if s is None else pd.concat([s[~s.index.isin(r.index)], r]).sort_index()
            status = "ok" if len(s) >= 2 else status
        item = {"id": ind["id"], "status": status}
        if status != "missing":
            series[ind["id"]] = s
            item.update(summarize(s, ind))
            fc = ind.get("forecast")
            if fc and fc["code"] in fred_raw:
                pts = forecast_points(fred_raw[fc["code"]], ind, s.index[-1])
                if pts:
                    item["forecast"] = {"label": fc["label"], "points": pts}
        if status != "ok":
            item["error"] = errors.get(ind["code"], errors.get("yahoo", "알 수 없음"))
        items.append(item)

    counts = {k: sum(i["status"] == k for i in items) for k in ("ok", "stale", "missing")}
    latest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": counts,
        "indicators": items,
        "curve": build_curve(registry.get("curve", []), fred_raw),
    }
    return latest, series


def write_output(out_dir, registry, latest, series):
    out = Path(out_dir)
    (out / "series").mkdir(parents=True, exist_ok=True)
    decimals = {i["id"]: i.get("decimals", 2) for i in registry["indicators"]}
    for ind_id, s in series.items():
        with open(out / "series" / f"{ind_id}.json", "w", encoding="utf-8") as f:
            json.dump(series_json(ind_id, s, decimals[ind_id]), f, ensure_ascii=False, separators=(",", ":"))
    with open(out / "latest.json", "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, separators=(",", ":"))
    shutil.copyfile(REGISTRY_PATH, out / "indicators.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description="글로벌 경제 지표 수집")
    parser.add_argument("--out", default="site/data")
    args = parser.parse_args(argv)

    registry = load_registry()
    latest, series = collect(registry,
                             fred_key=os.environ.get("FRED_API_KEY", "").strip() or None,
                             previous_url=os.environ.get("PREVIOUS_DATA_URL", "").strip() or None)
    prev_url = os.environ.get("PREVIOUS_DATA_URL", "").strip()
    prev_latest = None
    if prev_url:
        try:
            r = _session().get(f"{prev_url.rstrip('/')}/latest.json", timeout=HTTP_TIMEOUT)
            prev_latest = r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            pass
    releases.annotate(registry, latest, prev_latest, session=_session())
    c = latest["counts"]
    total = len(registry["indicators"])
    print(f"정상 {c['ok']} · 이전 값 유지 {c['stale']} · 없음 {c['missing']} (전체 {total})")
    gha = bool(os.environ.get("GITHUB_ACTIONS"))
    defs = {i["id"]: i for i in registry["indicators"]}
    for item in latest["indicators"]:
        if "last" in item:
            d = defs[item["id"]]
            ch = item["changes"]["prev"]
            delta = "" if ch is None else format(ch["value"], "+.2f")
            print(f"  {d['name']:<14} {item['last']['date']}  {item['last']['value']:>14,.4f}"
                  f"  {delta} {d['change']}  σ={item['sigma']}  {item['status']}")
    for item in latest["indicators"]:
        if item["status"] != "ok":
            print(f"{'::warning::' if gha else '경고: '}{item['id']} {item['status']}: {item.get('error')}")

    if c["ok"] == 0:
        print("수집된 지표가 하나도 없습니다. 배포하지 않습니다.")
        return 1
    write_output(args.out, registry, latest, series)
    print(f"저장 완료: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
